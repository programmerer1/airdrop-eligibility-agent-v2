import json
import asyncio
import logging
from eth_abi import encode
from eth_utils import keccak, to_checksum_address
from typing import List, Dict, Any, Optional 
import datetime

from src import services 
from src.providers.api_client_interface import AbstractAPIClient

logger = logging.getLogger(__name__)

class EligibilityApi:
    """
    Проверяет право пользователя на эирдроп, вызывая eth_call 
    через например через EtherscanAPIClient. Ожидает, что функция проверки
    принимает один аргумент типа 'address'.
    """

    def __init__(self, contracts: List[Dict[str, Any]], api_client: AbstractAPIClient) -> None:
        """
        Инициализирует API.
        
        :param contracts: Список словарей с информацией о контрактах.
        :param api_client: реализация AbstractAPIClient. Внимание: должен поддерживать eth_call.
        """
        self.contracts = contracts
        self._api = api_client 

    async def _query_contract(self, contract: dict, user_address_checksummed: str) -> dict: # Принимаем уже проверенный адрес
        """
        Запрашивает один контракт через eth_call, проверяя ABI.
        """
        name = contract.get("contract_name")
        address = contract.get("contract_address")
        chain_id = contract.get("chain_id") 
        abi_string = contract.get("eligibility_function_abi")
        decimals = 18 
        ticker = contract.get("token_ticker")

        # Проверка и установка decimals
        try:
             decimals_raw = contract.get("token_decimals")
             if decimals_raw is not None:
                 decimals = int(decimals_raw)
        except (ValueError, TypeError):
             logger.warning(f"[{name}] Invalid token_decimals format: {contract.get('token_decimals')}. Using default {decimals}.")

        # Парсинг ABI
        try:
            json_abi = json.loads(abi_string) 
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[{name}] Invalid ABI format: {e} — skipped.")
            return {"status": "skipped", "contract": name}

        # --- Строгая проверка ABI ---
        if not isinstance(json_abi, dict) or json_abi.get("type") != "function":
            logger.warning(f"[{name}] ABI is not a valid function object — skipped.")
            return {"status": "skipped", "contract": name}

        method = json_abi.get("name")
        inputs = json_abi.get("inputs", [])
        
        # Проверяем, что функция принимает ровно один аргумент типа address
        if len(inputs) != 1 or inputs[0].get("type") != "address":
            logger.warning(f"[{name}] Function ABI does not match expected signature (one 'address' input). Inputs: {inputs} — skipped.")
            return {"status": "skipped", "contract": name}
            
        input_type = inputs[0]["type"]

        # Подготовка данных для eth_call
        try:
            # Используем уже проверенный checksum-адрес напрямую
            call_data = self._prepare_call_data(method, [input_type], [user_address_checksummed]) 
        except Exception as e:
            logger.warning(f"[{name}] Failed to encode call data: {e} — skipped.")
            return {"status": "skipped", "contract": name}

        # Вызов eth_call через API клиент
        hex_result: Optional[str] = None
        try:
            hex_result = await self._api.eth_call(
                chain_id=chain_id,
                to_address=address,
                data=call_data
            )
        except Exception as e:
             logger.error(f"[{name} @ Chain {chain_id}] API client error during eth_call: {e}")
             return {"status": "skipped", "contract": name}

        # Парсинг ответа
        if not hex_result or hex_result == "0x":
            logger.info(f"[{name}] eth_call returned empty or zero result — skipped.")
            return {"status": "skipped", "contract": name}

        try:
            value_int = int(hex_result, 16)
        except ValueError:
            logger.warning(f"[{name}] Invalid non-zero hex value in response: {hex_result} — skipped.")
            return {"status": "skipped", "contract": name}

        if value_int == 0:
            logger.info(f"[{name}] Returned zero value — skipped.")
            return {"status": "skipped", "contract": name}

        value = value_int / (10 ** decimals)
        formatted_amount = f"{value:.6f}".rstrip('0').rstrip('.') if '.' in f"{value:.6f}" else f"{value}"

        logger.info(f"[{name} @ Chain {chain_id}] Success! Amount: {formatted_amount} {ticker}")

        return {
            "status": "ok",
            "contract": name,
            "contract_address": address,
            "chain_id": chain_id,
            "eligible": True,
            "amount": f"{formatted_amount} {ticker}",
            "claim_start_date": self.format_timestamp_utc(contract.get("claim_start_timestamp")),
            "claim_end_date": self.format_timestamp_utc(contract.get("claim_end_timestamp")),
            "token_security": self.format_security_status(int(contract.get("token_analysis_status")))
        }

    @staticmethod
    def _prepare_call_data(method_name: str, input_types: list, processed_params: list) -> str:
        """
        Готовит поле 'data' для eth_call (селектор + кодированные аргументы).
        """
        function_signature = f"{method_name}({','.join(input_types)})"
        selector = keccak(text=function_signature)[:4]
        encoded_args = encode(input_types, processed_params)
        return "0x" + (selector + encoded_args).hex()
        
    @staticmethod
    def format_timestamp_utc(timestamp):
        if (not timestamp) or (not isinstance(timestamp, (int, float))) or (timestamp <= 0):
            return "Could not find"

        utc_dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        readable_format = utc_dt.strftime("%Y-%m-%d %H:%M UTC")
        return readable_format

    @staticmethod
    def format_security_status(security_status_code: int) -> str:
        status_map = {
            0: "The token's source code has not been audited",
            1: "Contract code did not compile"
            2: "Suspicious",
            3: "Unsafe",
            4: "Caution",
            5: "Verified Safe"
        }
        
        return status_map.get(security_status_code, "Unknown")    

    async def check_eligibility(self, user_address: str) -> dict:
        """
        Публичный метод: проверяет право на всех EVM-контрактах.
        Возвращает только 'ok' результаты.
        """
        try:
            valid_user_address = to_checksum_address(user_address)
        except ValueError:
            logger.error(f"Invalid user address provided: {user_address}")
            return {"wallet": user_address, "results": []}

        # Передаем уже проверенный адрес в _query_contract
        tasks = [self._query_contract(c, valid_user_address) for c in self.contracts] 
        results = await asyncio.gather(*tasks)

        ok_results = [r for r in results if r.get("status") == "ok"]

        return {"wallet": valid_user_address, "results": ok_results}
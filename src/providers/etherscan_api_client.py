import asyncio
import logging
import httpx
import json
from typing import Dict, Any, Optional
from .api_client_interface import AbstractAPIClient 

logger = logging.getLogger(__name__)

class EtherscanAPIError(Exception):
    """Кастомное исключение для всех ошибок API Etherscan."""
    pass

class EtherscanAPIClient(AbstractAPIClient):
    """
    Реализация API клиента для Etherscan v2.
    """
    def __init__(self, 
                 base_url: str, 
                 api_key: str, 
                 delay_seconds: float = 1.0, 
                 lock: asyncio.Lock = asyncio.Lock(),
                 timeout: int = 15,
                 proxy_url: Optional[str] = None):
        
        self._base_url = base_url
        self._api_key = api_key
        self._delay = delay_seconds # Эта задержка не используется напрямую, но нужна для _lock
        self._timeout = timeout

        proxy = proxy_url or None
        self._client = httpx.AsyncClient(timeout=timeout, proxy=proxy)
        self._last_request_time = 0
        self._lock = lock # Общая блокировка

    async def _request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Приватный метод для выполнения запросов с учетом rate-лимита.
        """
        async with self._lock:
            # Расчет задержки (используем self._delay из config)
            now = asyncio.get_event_loop().time()
            time_since_last = now - self._last_request_time
            sleep_duration = 0
            
            if time_since_last < self._delay: 
                sleep_duration = self._delay - time_since_last
                await asyncio.sleep(sleep_duration)
            
            self._last_request_time = now + sleep_duration
            
            params['apikey'] = self._api_key
        
            try:
                response = await self._client.get(self._base_url, params=params)
                response.raise_for_status() 
                data = response.json()
                
                if 'status' in data and data['status'] == '0':
                    error_message = f"Etherscan API Error: {data.get('message')} - {data.get('result')}"
                    logger.warning(error_message)
                    raise EtherscanAPIError(error_message)
                     
                if 'result' not in data:
                     error_message = f"Invalid API response: 'result' not in data. Response: {data}"
                     logger.error(error_message)
                     raise EtherscanAPIError(error_message)
                     
                return data

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error for {e.request.url}: {e.response.status_code} - {e.response.text}")
                raise EtherscanAPIError(f"HTTP error: {e.response.status_code}") from e
            except httpx.RequestError as e:
                logger.error(f"Network error for {e.request.url}: {e}")
                raise EtherscanAPIError(f"Network error: {e}") from e
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON response: {e}")
                raise EtherscanAPIError(f"JSON decode error: {e}") from e


    async def get_latest_block_number(self, chain_id: int) -> int:
        # ... (код без изменений) ...
        params = {
            "chainid": chain_id,
            "module": "proxy",
            "action": "eth_blockNumber"
        }
        data = await self._request(params)
        return int(data['result'], 16)

    async def get_block_by_number(self, chain_id: int, block_number: int) -> Optional[Dict[str, Any]]:
        # ... (код без изменений) ...
        params = {
            "chainid": chain_id,
            "module": "proxy",
            "action": "eth_getBlockByNumber",
            "tag": hex(block_number),
            "boolean": "true"
        }
        data = await self._request(params)
        return data.get('result')
    
    async def get_transaction_receipt(self, chain_id: int, tx_hash: str) -> Optional[Dict[str, Any]]:
        # ... (код без изменений) ...
        params = {
            "chainid": chain_id,
            "module": "proxy",
            "action": "eth_getTransactionReceipt",
            "txhash": tx_hash
        }
        data = await self._request(params)
        return data.get('result')

    async def get_contract_source(self, chain_id: int, contract_address: str) -> Optional[Dict[str, Any]]:
        # ... (код без изменений) ...
        params = {
            "chainid": chain_id,
            "module": "contract",
            "action": "getsourcecode",
            #"contractaddress": contract_address
            "address": contract_address
        }
        data = await self._request(params)
        result_list = data.get('result')
        if isinstance(result_list, list) and len(result_list) > 0:
            return result_list[0]
        
        logger.warning(f"Could not get source code for {contract_address} on chain {chain_id}. Result: {result_list}")
        return None
        
    # --- НОВЫЙ МЕТОД: Реализация eth_call ---
    async def eth_call(self, chain_id: int, to_address: str, data: str) -> Optional[str]:
        """
        Выполняет eth_call.
        """
        params = {
            "chainid": chain_id,
            "module": "proxy",
            "action": "eth_call",
            "to": to_address,
            "data": data,
            "tag": "latest" # Обычно читаем из последнего блока
        }
        try:
            # Используем _request для rate-лимита и обработки ошибок
            response_data = await self._request(params) 
            result = response_data.get('result')
            # Проверяем, что результат - не строка с ошибкой и не пустой
            if isinstance(result, str) and result.startswith("0x") and len(result) > 2:
                return result
            else:
                logger.warning(f"eth_call for {to_address} (data: {data[:10]}...) returned invalid result: {result}")
                return None
        except EtherscanAPIError as e:
            logger.error(f"eth_call failed for {to_address} (data: {data[:10]}...): {e}")
            return None # Не выбрасываем исключение, просто возвращаем None

    async def eth_getCode(self, chain_id: int, address: str) -> Optional[str]:
        """
        Получает код, хранящийся по указанному адресу.
        """
        params = {
            "chainid": chain_id,
            "module": "proxy",
            "action": "eth_getCode",
            "address": address,
            "tag": "latest"
        }
        try:
            response_data = await self._request(params)
            result = response_data.get('result')
            # Проверяем, что результат - это hex-строка
            if isinstance(result, str) and result.startswith("0x"):
                return result # Возвращаем "0x" (пусто) или "0x123..." (код)
            else:
                logger.warning(f"eth_getCode for {address} returned invalid result: {result}")
                return None
        except EtherscanAPIError as e:
            # Не выбрасываем исключение, просто логируем и возвращаем None
            logger.error(f"eth_getCode failed for {address}: {e}")
            return None
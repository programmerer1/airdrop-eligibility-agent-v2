# src/providers/moralis_api_client.py
import asyncio
import logging
import httpx
import json
from typing import Dict, Any, Optional

from .api_client_interface import AbstractAPIClient 

logger = logging.getLogger(__name__)

# --- Ошибка API ---
class MoralisAPIError(Exception):
    """Кастомное исключение для всех ошибок API Moralis."""
    pass

# --- Маппинг ID сетей ---
def _chain_id_to_moralis_format(chain_id: int) -> str:
    """Преобразует числовой chain_id в hex-строку для Moralis."""
    return hex(chain_id)

class MoralisAPIClient(AbstractAPIClient):
    """
    Реализация API клиента для Moralis API.
    """
    def __init__(self, 
                 base_url: str, 
                 api_key: str, 
                 delay_seconds: float = 0.5,
                 lock: asyncio.Lock = asyncio.Lock(), 
                 timeout: int = 30,
                 proxy_url: Optional[str] = None):
        
        if not api_key:
            raise ValueError("Moralis API key is required.")
            
        self._base_url = base_url.rstrip('/')
        self._api_key = api_key
        self._delay = delay_seconds 
        self._timeout = timeout
        self._headers = {
            "accept": "application/json",
            "X-API-Key": self._api_key
        }
        self._post_headers = {**self._headers, "Content-Type": "application/json"}
        proxy = proxy_url or None
        self._client = httpx.AsyncClient(timeout=timeout, proxy=proxy)
        self._last_request_time = 0
        self._lock = lock 

    async def _request(self, method: str, endpoint: str, 
                       params: Optional[Dict[str, Any]] = None, 
                       json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self._base_url}{endpoint}"
        async with self._lock:
            now = asyncio.get_event_loop().time()
            time_since_last = now - self._last_request_time
            sleep_duration = 0
            if time_since_last < self._delay: 
                sleep_duration = self._delay - time_since_last
                await asyncio.sleep(sleep_duration + 0.01) 
            self._last_request_time = now + sleep_duration
            try:
                if method.upper() == 'GET':
                    response = await self._client.get(url, params=params, headers=self._headers)
                elif method.upper() == 'POST':
                    response = await self._client.post(url, json=json_data, headers=self._post_headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                response.raise_for_status() 
                if response.status_code == 204: return {} 
                data = response.json()
                if isinstance(data, dict) and data.get('message'):
                    is_likely_error = all(k in ['message', 'name', 'description', 'code'] for k in data.keys())
                    if is_likely_error:
                         error_message = f"Moralis API Error: {data.get('message')} (Code: {data.get('code')})"
                         logger.warning(error_message)
                         raise MoralisAPIError(error_message)
                return data
            except httpx.HTTPStatusError as e:
                error_body = e.response.text
                logger.error(f"HTTP error {e.response.status_code} for {e.request.url}: {error_body}")
                raise MoralisAPIError(f"HTTP error: {e.response.status_code} - {error_body}") from e
            except httpx.RequestError as e:
                logger.error(f"Network error for {e.request.url}: {e}")
                raise MoralisAPIError(f"Network error: {e}") from e
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode Moralis JSON response: {e}")
                raise MoralisAPIError(f"JSON decode error: {e}") from e


    async def get_latest_block_number(self, chain_id: int) -> int:
        message = "MoralisAPIClient does not support this operation now."
        logger.error(message)
        raise NotImplementedError(message)


    async def get_block_by_number(self, chain_id: int, block_number: Any) -> Optional[Dict[str, Any]]:
        message = "MoralisAPIClient does not support this operation now."
        logger.error(message)
        raise NotImplementedError(message)


    async def get_transaction_receipt(self, chain_id: int, tx_hash: str) -> Optional[Dict[str, Any]]:
        message = "MoralisAPIClient does not support this operation now."
        logger.error(message)
        raise NotImplementedError(message)


    async def get_contract_source(self, chain_id: int, contract_address: str) -> Optional[Dict[str, Any]]:
        message = "MoralisAPIClient does not support fetching contract source code."
        logger.error(message)
        raise NotImplementedError(message)


    async def eth_call(self, chain_id: int, to_address: str, data: str) -> Optional[str]:
        message = "MoralisAPIClient does not support direct eth_call with raw data."
        logger.error(message)
        raise NotImplementedError(message)
    
    async def eth_getCode(self, chain_id: int, address: str) -> Optional[str]:
        message = "MoralisAPIClient does not support direct eth_call with raw data."
        logger.error(message)
        raise NotImplementedError(message)

    async def get_token_metadata(self, chain_id: int, token_address: str) -> Optional[Dict[str, Any]]:
        """
        Получает метаданные ERC20 токена, включая symbol, decimals и security info.
        """
        chain_hex = _chain_id_to_moralis_format(chain_id)
        endpoint = f"/erc20/metadata"
        params = {
            "chain": chain_hex,   
            "addresses[0]": token_address
        }
        try:
            # Moralis возвращает массив, даже если адрес один
            response_data = await self._request("GET", endpoint, params=params)
            if isinstance(response_data, list) and len(response_data) > 0:
                # Берем первый элемент
                metadata = response_data[0] 
                
                # Проверяем наличие нужных полей (symbol/decimals обязательны для успеха)
                if metadata.get('symbol') and metadata.get('decimals') is not None:
                    # Добавляем security_score, если он есть (он может отсутствовать)
                    security_info = metadata.get('verified_contract_security_score') # Имя поля может отличаться
                    metadata['security_score'] = security_info if security_info else None
                    return metadata
                else:
                    logger.warning(f"Moralis metadata for {token_address} missing symbol or decimals. Response: {metadata}")
                    return None
            else:
                 logger.warning(f"Moralis returned empty or invalid metadata for {token_address}. Response: {response_data}")
                 return None
                 
        except MoralisAPIError as e:
            # Ошибки (404, rate limit и т.д.) будут пойманы здесь
            logger.error(f"Failed to get Moralis metadata for token {token_address} on chain {chain_id}: {e}")
            # Выбрасываем исключение, чтобы транзакция откатилась
            raise
import asyncio
import logging
import httpx
import json
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class OpenAIAPIError(Exception):
    """Кастомное исключение для всех ошибок OpenAI-совместимого API."""
    pass

class OpenAICompatibleClient:
    """
    Клиент для OpenAI-совместимых API (LLM).
    """
    def __init__(self, 
                 base_url: str, 
                 api_key: str, 
                 model: str,
                 lock: asyncio.Lock,
                 timeout: int = 180,
                 proxy_url: Optional[str] = None):
        
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._lock = lock

        proxy = proxy_url or None
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"
            },
            proxy=proxy
        )
        logger.info(f"OpenAICompatibleClient initialized for model {model} at {base_url}.")

    async def query(self, payload: Dict[str, Any]) -> Optional[str]:
        """
        Отправляет payload (промпт) модели и возвращает ответ.
        
        :param payload: Словарь с "messages", "response_format", и т.д.
        :return: Строка с ответом (content) от LLM.
        """
        
        # Добавляем модель в payload
        payload['model'] = self._model
        
        # Используем общую блокировку (хотя для LLM лимиты обычно выше)
        async with self._lock:
            try:
                response = await self._client.post(self._base_url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                
                if not data.get('choices') or not data['choices'][0].get('message'):
                    raise OpenAIAPIError(f"Invalid LLM response structure: {data}")
                    
                content = data['choices'][0]['message'].get('content')
                return content.strip() if content else None

            except httpx.HTTPStatusError as e:
                error_body = e.response.text
                logger.error(f"LLM HTTP error {e.response.status_code}: {error_body}")
                raise OpenAIAPIError(f"HTTP error: {e.response.status_code} - {error_body}") from e
            except httpx.RequestError as e:
                logger.error(f"LLM Network error for {e.request.url}: {e}")
                raise OpenAIAPIError(f"Network error: {e}") from e
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode LLM JSON response: {e}")
                raise OpenAIAPIError(f"JSON decode error: {e}") from e
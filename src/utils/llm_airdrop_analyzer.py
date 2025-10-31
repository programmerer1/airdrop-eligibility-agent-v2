import logging
import json
from typing import Dict, Any, Optional

from ..providers.openai_compatible_api_client import OpenAICompatibleClient, OpenAIAPIError
from .prompts.airdrop_contract_scanner_analyzer import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

class LLMAirdropAnalyzer:
    """
    Использует LLM-клиент для анализа исходного кода и ABI контракта
    на предмет логики Airdrop.
    """
    def __init__(self, client: OpenAICompatibleClient):
        self._client = client
        logger.info("LLMAirdropAnalyzer initialized.")

    def _flatten_source_code(self, source_code_json: str) -> str:
        """
        Преобразует JSON с исходным кодом в единую строку.
        """
        try:
            data = json.loads(source_code_json)
        except json.JSONDecodeError:
            logger.warning("Failed to parse source_code JSON for LLM. Sending raw.")
            return source_code_json

        if 'source' in data:
            return data['source']

        if 'sources' in data:
            # Объединяем все файлы в одну строку
            all_code = []
            for file_path, content_obj in data['sources'].items():
                all_code.append(f"// --- File: {file_path} ---\n\n")
                all_code.append(content_obj.get('content', ''))
                all_code.append("\n\n")
            return "".join(all_code)
        
        logger.warning("Unknown source_code structure for LLM. Sending raw.")
        return source_code_json

    def _prepare_payload(self, source_code_json: str, abi_json: str) -> Dict[str, Any]:
        """
        Готовит полный payload (json-запрос) для OpenAI-совместимого API.
        """
        # 1. Сплющиваем исходный код
        flat_source_code = self._flatten_source_code(source_code_json)
        
        # 2. Формируем user prompt
        user_content = (
            "Here is the smart contract source code:\n"
            "```solidity\n"
            f"{flat_source_code}\n"
            "```\n\n"
            "Here is the smart contract ABI:\n"
            "```json\n"
            f"{abi_json}\n"
            "```\n\n"
            "Analyze the contract based on your instructions and provide ONLY the JSON response."
        )
        
        # 3. Собираем payload
        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            # Эта опция заставляет модель гарантированно вернуть JSON
            "response_format": {"type": "json_object"} 
        }
        return payload

    def _validate_llm_response(self, response_str: str) -> Optional[Dict[str, Any]]:
        """
        Валидирует ответ от LLM.
        """
        try:
            data = json.loads(response_str)
        except json.JSONDecodeError:
            logger.warning(f"LLM response was not valid JSON. Response: {response_str[:200]}")
            return None # Не JSON
            
        if not isinstance(data, dict):
            logger.warning(f"LLM response was not a JSON object. Response: {data}")
            return None # Не объект

        if not data:
            logger.info("LLM returned an empty JSON object. Contract is not an airdrop.")
            return None # Пустой JSON {}
            
        # ГЛАВНАЯ ПРОВЕРКА: наличие обязательного поля
        if 'eligibility_function_abi' not in data:
            logger.warning(f"LLM response is missing required key 'eligibility_function_abi'. Response: {data}")
            return None
            
        logger.info(f"LLM validation successful. Found eligibility function.")
        return data

    async def analyze_contract(self, source_code_json: str, abi_json: str) -> Optional[Dict[str, Any]]:
        """
        Выполняет полный цикл анализа LLM.
        
        :return: Словарь с данными, если это Airdrop, иначе None.
        """
        try:
            payload = self._prepare_payload(source_code_json, abi_json)
            llm_response_str = await self._client.query(payload)
            
            if not llm_response_str:
                logger.warning("LLM client returned an empty response.")
                return None
                
            return self._validate_llm_response(llm_response_str)
            
        except OpenAIAPIError as e:
            # Ошибка API, таймаут, и т.д.
            logger.error(f"LLM API error during analysis: {e}")
            # Выбрасываем исключение, чтобы транзакция откатилась
            raise
        except Exception as e:
            logger.error(f"Unexpected error during LLM analysis: {e}", exc_info=True)
            # Выбрасываем исключение, чтобы транзакция откатилась
            raise
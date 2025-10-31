import json
from src.agent.prompts.extractor import system_prompt
from eth_utils import is_address
from src.services import extractor_client_llm
import logging

logger = logging.getLogger(__name__)

class Extractor:
    async def extract(self, prompt: str) -> dict:
        payload = {
            "max_tokens" : 2000,
            "top_p" : 1,
            "presence_penalty" : 0,
            "frequency_penalty" : 0,
            "temperature" : 0.0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
        }

        content = await extractor_client_llm.query(payload)

        if not content:
            logger.warning("Extractor LLM returned empty content")
            return None

        try:
            data = json.loads(content)
            return self.normalize_response(data)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from Extractor LLM. Content: {content[:100]}... Error: {e}")
            return None # Возвращаем None при ошибке парсинга

    def normalize_response(self, data: dict) -> Optional[str]:
            if not data:
                return None

            address = data.get("address")

            if not address:
                logger.warning(f"Extractor LLM did not return the address: {address}")
                return None

            if not is_address(address):
                logger.warning(f"Extractor LLM extracted an invalid address: {address}")
                return None
                
            return address
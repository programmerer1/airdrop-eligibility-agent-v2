import json
from src.agent.prompts.extractor import system_prompt
from eth_utils import is_address
from src.services import extractor_client_llm

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
        return self.normalize_response(json.loads(content))

    def normalize_response(self, data: dict) -> dict:
        if not data:
            return {}

        address = data.get("address", {})

        if not address:
            return {}

        if not is_address(address):
            return {}
            
        return address
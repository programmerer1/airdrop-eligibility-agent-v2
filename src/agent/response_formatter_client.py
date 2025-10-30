import json
from src.agent.prompts.formatter import system_prompt, user_prompt_template
from src.services import response_formatter_client_llm

class ResponseFormatter:
    async def format(self, result: dict, user_prompt: str) -> str:
        system_instruction = {
            "role": "system",
            "content": system_prompt
        }

        user_message = {
            "role": "user",
            "content": user_prompt_template.format(
                user_prompt=user_prompt,
                result=result
            )
        }

        payload = {
            "max_tokens" : 8192,
            "top_p" : 1,
            "presence_penalty" : 0,
            "frequency_penalty" : 0,
            "temperature" : 0.0,
            "messages": [
                system_instruction,
                user_message
            ]
        }

        return await response_formatter_client_llm.query(payload)

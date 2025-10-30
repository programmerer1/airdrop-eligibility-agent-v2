from config import CORS_ORIGINS, CORS_METHODS, CORS_HEADERS, CORS_CREDENTIALS
from sentient_agent_framework.implementation.default_server import DefaultServer
from agent.agent import Agent
from fastapi.middleware.cors import CORSMiddleware

class AgentServer(DefaultServer):
    def __init__(self, agent: Agent):
        super().__init__(agent)
        
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=self.parse_list_env(CORS_ORIGINS),
            allow_credentials=CORS_CREDENTIALS,
            allow_methods=self.parse_list_env(CORS_METHODS),
            allow_headers=self.parse_list_env(CORS_HEADERS),
        )

    @staticmethod
    def parse_list_env(value_str):
        return [item.strip() for item in value_str.split(',') if item.strip()]
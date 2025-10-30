from dotenv import load_dotenv
import logging
from src.agent.agent import Agent
from src.agent_server import AgentServer
load_dotenv()

from src.config import APP_HOST, APP_PORT, APP_ENV

if APP_ENV == 'prod':
    log_level = logging.WARNING
    log_level_name = 'WARNING'
else:
    # dev
    log_level = logging.INFO
    log_level_name = 'INFO'

logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.info(f"Logging level set to {log_level_name} based on APP_ENV='{APP_ENV}'")

if __name__ == "__main__":
    # Запуск сервера агента
    server = AgentServer(Agent())
    server.run(host=APP_HOST, port=APP_PORT)
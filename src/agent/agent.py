import json
import logging
from typing import Any

from sentient_agent_framework.interface.agent import AbstractAgent
from sentient_agent_framework.interface.request import Query
from sentient_agent_framework.interface.session import Session
from sentient_agent_framework.interface.response_handler import ResponseHandler

from src.agent.extractor_client import Extractor
from src.agent.response_formatter_client import ResponseFormatter
from src.agent.eligibility_api import EligibilityApi
from src.services import db_connector, agent_evm_api_client
from src.agent.mysql_cache import MySQLCache
from src.agent.contract_repository import ContractRepository

logger = logging.getLogger(__name__)

class Agent(AbstractAgent):
    def __init__(self, name: str = "Airdrop Eligibility Agent") -> None:
        super().__init__(name)
        self.extractor = Extractor()
        self.formatter = ResponseFormatter()
        self.cache = MySQLCache(db_connector, default_ttl_hours=1)
        self.contract_repo = ContractRepository(db_connector)

    async def assist(self, session: Session, query: Query, response_handler: ResponseHandler) -> None:
        try:
            prompt = getattr(query, "prompt", "") or ""
            if not prompt:
                await response_handler.emit_error("Empty prompt", details={"field": "prompt"})
                return

            # Using the model, we extract data from the user's request.
            address = await self.extractor.extract(prompt)

            if not address:
                await response_handler.emit_error("Address is invalid or not provided", details={"field": "address"})
                return

            cache_key = f"evm:{address}"
            data = await self.cache.get(cache_key)

            if not data:
                contracts = await self.contract_repo.getContracts()
                eligibility_api = EligibilityApi(contracts, agent_evm_api_client)
                data = await eligibility_api.check_eligibility(address)
                await self.cache.set(cache_key, json.dumps(data))

            report = await self.formatter.format(json.dumps(data, indent=2), prompt)
            await response_handler.respond("response", report)
        except Exception as exc:
            logger.error("Something went wrong.", exc_info=True)
            await response_handler.emit_error(
                "Something went wrong. Please try again later.",
                details={"stage": "respond", "error_type": type(exc).__name__}
            )
            
        finally:
            await response_handler.complete()

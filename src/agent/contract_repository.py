import json
from src.db_class.mysql_connector import MySQLConnector
from typing import List, Dict, Any
import aiomysql

class ContractRepository:
    def __init__(self, connector: MySQLConnector):
        self.connector = connector

    async def getContracts(self)-> List[Dict[str, Any]]:
        query = "SELECT c.contract_address, c.eligibility_function_abi, c.claim_start_timestamp, c.claim_end_timestamp, c.contract_name, c.token_address, c.token_ticker, c.token_decimals, c.token_analysis_status, c.evm_network_chain_id as chain_id FROM evm_airdrop_eligibility_contract c WHERE c.active_status=1 AND c.token_analysis_status NOT IN (1,2,3);"
        results: List[Dict[str, Any]] = []

        pool = await self.connector.init_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query)
                results = await cur.fetchall()
        
            return results or []
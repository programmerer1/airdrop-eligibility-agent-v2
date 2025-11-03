import logging
import json
import time
from typing import List, Dict, Any, Optional
import aiomysql
from ..base_repository import BaseRepository

logger = logging.getLogger(__name__)

class EvmTokenScannerRepository(BaseRepository):
    """
    Репозиторий для EvmTokenScanner.
    """

    async def get_unverified_tokens_data(self, conn: aiomysql.Connection, batch_size: int) -> List[Dict[str, Any]]:
        sql = """
            SELECT id, token_address, evm_network_chain_id, token_security_report
            FROM evm_airdrop_eligibility_contract
            WHERE active_status = 1 AND token_analysis_status = 0 AND token_address IS NOT NULL
            LIMIT %s FOR UPDATE SKIP LOCKED
        """
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, (batch_size,))
            return await cursor.fetchall()

    async def update_token_analysis_status(self, conn: aiomysql.Connection, id: int, security_status: int, token_security_report: str):
        active_status = 1

        if security_status in [1, 2, 3]:
            active_status = 0
        
        sql = f"""UPDATE evm_airdrop_eligibility_contract 
              SET token_analysis_status = %s, token_security_report = %s, active_status = %s WHERE id = %s
        """
        
        params = (security_status, token_security_report, active_status, id)
        
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params)
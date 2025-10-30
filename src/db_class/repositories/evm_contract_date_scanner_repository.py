import logging
from typing import List, Dict, Any, Optional
import aiomysql
from ..base_repository import BaseRepository

logger = logging.getLogger(__name__)

class EvmContractDateScannerRepository(BaseRepository):
    """
    Репозиторий для EvmContractDateScanner.
    """

    async def deactivate_expired_contracts(self) -> int:
        """
        ШАГ 1: Деактивирует контракты, у которых истек claim_end_timestamp.
        """
        sql = """
            UPDATE evm_airdrop_eligibility_contract
            SET active_status = 0
            WHERE active_status = 1
              AND claim_end_timestamp IS NOT NULL
              AND claim_end_timestamp <= CURRENT_TIMESTAMP;
        """
        affected_rows = 0
        async with (await self.pool).acquire() as conn:
            await conn.begin() 
            try:
                async with conn.cursor() as cursor:
                    await cursor.execute(sql)
                    affected_rows = cursor.rowcount
                await conn.commit() 
            except Exception as e:
                await conn.rollback() 
                logger.error(f"Failed to execute deactivate_expired_contracts: {e}")
                raise 
        return affected_rows

    async def get_contracts_for_code_check(self, conn: aiomysql.Connection, batch_size: int) -> List[Dict[str, Any]]:
        """
        ШАГ 2: Выбирает ВСЕ активные контракты, где claim_end_timestamp IS NULL,
        для проверки eth_getCode.
        """
        sql = """
            SELECT id, evm_network_chain_id, contract_address
            FROM evm_airdrop_eligibility_contract
            WHERE active_status = 1
              AND claim_end_timestamp IS NULL
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        """
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, (batch_size,))
            return await cursor.fetchall()
            
    async def get_contracts_for_claim_start_check(self, conn: aiomysql.Connection, batch_size: int) -> List[Dict[str, Any]]:
        """
        ШАГ 4: Выбирает контракты, где нужно проверить claim_start_timestamp.
        """
        sql = """
            SELECT id, evm_network_chain_id, contract_address, claim_start_getter_abi
            FROM evm_airdrop_eligibility_contract
            WHERE active_status = 1
              AND claim_start_timestamp IS NULL
              AND claim_start_getter_abi IS NOT NULL
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        """
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, (batch_size,))
            return await cursor.fetchall()

    async def get_contracts_for_claim_end_check(self, conn: aiomysql.Connection, batch_size: int) -> List[Dict[str, Any]]:
        """
        ШАГ 3: Выбирает (уже проверенные на eth_getCode) контракты, 
        где нужно получить claim_end_timestamp.
        """
        sql = """
            SELECT id, evm_network_chain_id, contract_address, claim_end_getter_abi
            FROM evm_airdrop_eligibility_contract
            WHERE active_status = 1
              AND claim_end_timestamp IS NULL
              AND claim_end_getter_abi IS NOT NULL
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        """
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, (batch_size,))
            return await cursor.fetchall()

    async def deactivate_contract_batch(self, conn: aiomysql.Connection, contract_ids: List[int]):
        if not contract_ids:
            return
        format_strings = ','.join(['%s']*len(contract_ids))
        sql = f"UPDATE evm_airdrop_eligibility_contract SET active_status = 0 WHERE id IN ({format_strings})"
        async with conn.cursor() as cursor:
            await cursor.execute(sql, (*contract_ids,))
            
    async def update_claim_start_timestamp(self, conn: aiomysql.Connection, contract_id: int, timestamp: int):
        sql = "UPDATE evm_airdrop_eligibility_contract SET claim_start_timestamp = FROM_UNIXTIME(%s) WHERE id = %s"
        async with conn.cursor() as cursor:
            await cursor.execute(sql, (timestamp, contract_id))

    async def invalidate_claim_start_abi(self, conn: aiomysql.Connection, contract_id: int):
        sql = "UPDATE evm_airdrop_eligibility_contract SET claim_start_getter_abi = NULL WHERE id = %s"
        async with conn.cursor() as cursor:
            await cursor.execute(sql, (contract_id,))

    async def update_claim_end_timestamp(self, conn: aiomysql.Connection, contract_id: int, timestamp: int, active_status: int):
        sql = "UPDATE evm_airdrop_eligibility_contract SET claim_end_timestamp = FROM_UNIXTIME(%s), active_status = %s WHERE id = %s"
        async with conn.cursor() as cursor:
            await cursor.execute(sql, (timestamp, active_status, contract_id))

    async def invalidate_claim_end_abi(self, conn: aiomysql.Connection, contract_id: int):
        sql = "UPDATE evm_airdrop_eligibility_contract SET claim_end_getter_abi = NULL WHERE id = %s"
        async with conn.cursor() as cursor:
            await cursor.execute(sql, (contract_id,))
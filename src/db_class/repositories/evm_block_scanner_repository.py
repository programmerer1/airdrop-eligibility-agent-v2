import logging
from typing import List, Dict, Any, Tuple
import aiomysql
from ..base_repository import BaseRepository

logger = logging.getLogger(__name__)

class EvmBlockScannerRepository(BaseRepository):
    """
    Реализация репозитория для EvmBlockScanner.
    Инкапсулирует SQL-запросы, связанные с чтением evm_block 
    и записью в evm_block_create_contract_transaction.
    """

    async def lock_and_get_unprocessed_blocks(self, conn: aiomysql.Connection, batch_size: int) -> List[Dict[str, Any]]:
        """
        Выбирает и атомарно блокирует (SELECT ... FOR UPDATE) 
        пачку необработанных блоков.
        """
        sql = """
            SELECT b.id, b.evm_network_chain_id, b.block_number 
            FROM evm_block AS b
            WHERE b.processing_status = 0
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        """
        
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, (batch_size,))
            return await cursor.fetchall()

    async def batch_update_block_status(self, conn: aiomysql.Connection, block_ids: List[int], status: int):
        """
        Массово обновляет 'processing_status' для списка ID блоков.
        """
        if not block_ids:
            return

        format_strings = ','.join(['%s'] * len(block_ids))
        sql = f"UPDATE evm_block SET processing_status = %s WHERE id IN ({format_strings})"
        
        params = (status, *block_ids) 
        
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params)

    async def batch_insert_contract_txs(self, conn: aiomysql.Connection, txs_data: List[Tuple[int, int, str]]):
        """
        Выполняет массовую вставку транзакций создания контрактов.
        """
        if not txs_data:
            return
            
        sql = """
            INSERT IGNORE INTO evm_block_create_contract_transaction 
                (evm_block_id, evm_network_chain_id, transaction_hash) 
            VALUES (%s, %s, %s)
        """
        async with conn.cursor() as cursor:
            await cursor.executemany(sql, txs_data)

    async def mark_block_as_completed(self, conn: aiomysql.Connection, block_id: int):
        """
        Помечает ОДИН блок как полностью обработанный (status = 2).
        """
        sql = """
            UPDATE evm_block 
            SET processing_status = 2, discovered_at = CURRENT_TIMESTAMP 
            WHERE id = %s
        """
        async with conn.cursor() as cursor:
            await cursor.execute(sql, (block_id,))
            
    async def mark_blocks_as_completed_batch(self, conn: aiomysql.Connection, block_ids: List[int]):
        """
        Массово помечает список блоков как полностью обработанные (status = 2).
        """
        if not block_ids:
            return

        format_strings = ','.join(['%s'] * len(block_ids))
        sql = f"""
            UPDATE evm_block 
            SET processing_status = 2, discovered_at = CURRENT_TIMESTAMP 
            WHERE id IN ({format_strings})
        """
        
        params = (*block_ids,) 
        
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params)
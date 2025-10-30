# src/db_class/repositories/evm_scanner_repository.py
import logging
from typing import List, Dict, Any, Tuple
import aiomysql
from ..base_repository import BaseRepository

logger = logging.getLogger(__name__)

class EvmScannerRepository(BaseRepository):
    """
    Реализация репозитория для EvmScanner.
    """

    async def get_active_networks_to_scan(self) -> List[Dict[str, Any]]:
        # ... (код без изменений) ...
        sql = """
            SELECT chain_id, last_discovered_block_number, finality_depth 
            FROM evm_network 
            WHERE active_status = 1 AND processing_status = 0
        """
        async with (await self.pool).acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(sql)
                return await cursor.fetchall()

    async def start_network_processing(self, conn: aiomysql.Connection, chain_id: int):
        # ... (код без изменений) ...
        sql = "UPDATE evm_network SET processing_status = 1 WHERE chain_id = %s"
        async with conn.cursor() as cursor:
            await cursor.execute(sql, (chain_id,))

    # --- ИЗМЕНЕНО: Этот метод теперь только сбрасывает статус ---
    async def finish_network_processing(self, conn: aiomysql.Connection, chain_id: int):
        """
        Помечает сеть как "обработка завершена" (processing_status = 0).
        НЕ обновляет номер блока (это делается в update_network_last_block).
        """
        sql = """
            UPDATE evm_network 
            SET processing_status = 0, 
                discovered_at = CURRENT_TIMESTAMP
            WHERE chain_id = %s
        """
        async with conn.cursor() as cursor:
            await cursor.execute(sql, (chain_id,))

    # --- НОВЫЙ МЕТОД: Обновление блока в рамках транзакции ---
    async def update_network_last_block(self, conn: aiomysql.Connection, chain_id: int, last_block_number: int):
        """
        Обновляет номер последнего обработанного блока и время.
        Вызывается АТОМАРНО вместе с batch_insert_blocks.
        """
        sql = """
            UPDATE evm_network 
            SET discovered_at = CURRENT_TIMESTAMP, 
                last_discovered_block_number = %s 
            WHERE chain_id = %s
        """
        async with conn.cursor() as cursor:
            await cursor.execute(sql, (last_block_number, chain_id))
    # ---

    async def batch_insert_blocks(self, conn: aiomysql.Connection, blocks_data: List[Tuple[int, int, str]]):
        # ... (код без изменений) ...
        if not blocks_data:
            return
            
        sql = """
            INSERT IGNORE INTO evm_block (evm_network_chain_id, block_number, block_hash) 
            VALUES (%s, %s, %s)
        """
        async with conn.cursor() as cursor:
            await cursor.executemany(sql, blocks_data)
# src/db_class/repositories/evm_transaction_scanner_repository.py
import logging
from typing import List, Dict, Any
import aiomysql
from ..base_repository import BaseRepository

logger = logging.getLogger(__name__)

class EvmTransactionScannerRepository(BaseRepository):
    """
    Реализация репозитория для EvmTransactionScanner.
    Инкапсулирует SQL-запросы, связанные с чтением evm_block_create_contract_transaction
    и записью в evm_contract и evm_contract_source.
    """

    async def lock_and_get_unprocessed_txs(self, conn: aiomysql.Connection, batch_size: int) -> List[Dict[str, Any]]:
        """
        Выбирает и атомарно блокирует (SELECT ... FOR UPDATE) 
        пачку необработанных транзакций создания контрактов.
        """
        sql = """
            SELECT tx.id, tx.evm_network_chain_id, tx.transaction_hash 
            FROM evm_block_create_contract_transaction AS tx
            WHERE tx.processing_status = 0
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        """

        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, (batch_size,))
            return await cursor.fetchall()

    async def batch_update_tx_status(self, conn: aiomysql.Connection, tx_ids: List[int], status: int):
        """
        Массово обновляет 'processing_status' для списка ID транзакций.
        """
        if not tx_ids:
            return

        format_strings = ','.join(['%s'] * len(tx_ids))
        sql = f"UPDATE evm_block_create_contract_transaction SET processing_status = %s WHERE id IN ({format_strings})"
        
        params = (status, *tx_ids)
        
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params)

    async def save_contract_and_source(self, conn: aiomysql.Connection, 
                                       tx_id: int, 
                                       chain_id: int, 
                                       contract_address: str, 
                                       contract_name: str | None,
                                       source_code: str, 
                                       abi: str):
        """
        Атомарно сохраняет верифицированный контракт:
        1. Вставляет запись в evm_contract.
        2. Получает ID новой записи.
        3. Вставляет запись в evm_contract_source.
        4. Помечает транзакцию (tx_id) как завершенную (status = 2).
        """
        async with conn.cursor() as cursor:
            # 1. Вставляем контракт
            contract_sql = """
                INSERT INTO evm_contract 
                    (evm_block_create_contract_transaction_id, evm_network_chain_id, 
                     contract_address, source_code_verified_status, processing_status) 
                VALUES (%s, %s, %s, 1, 2)
            """
            await cursor.execute(contract_sql, (tx_id, chain_id, contract_address))
            
            # 2. Получаем ID
            new_contract_id = cursor.lastrowid
            
            # 3. Вставляем исходный код
            source_sql = """
                INSERT INTO evm_contract_source 
                    (evm_contract_id, evm_network_chain_id, contract_address, contract_name, source_code, abi) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            
            await cursor.execute(source_sql, (new_contract_id, chain_id, contract_address, contract_name, source_code, abi))
            
            # 4. Обновляем статус транзакции
            tx_sql = """
                UPDATE evm_block_create_contract_transaction 
                SET processing_status = 2, discovered_at = CURRENT_TIMESTAMP 
                WHERE id = %s
            """
            await cursor.execute(tx_sql, (tx_id,))

    async def save_unverified_contract(self, conn: aiomysql.Connection, tx_id: int, chain_id: int, contract_address: str):
        """
        Атомарно сохраняет не верифицированный контракт.
        (Этот метод не трогаем, т.к. он не пишет в evm_contract_source)
        """
        async with conn.cursor() as cursor:
            # 1. Вставляем контракт
            contract_sql = """
                INSERT INTO evm_contract 
                    (evm_block_create_contract_transaction_id, evm_network_chain_id, 
                     contract_address, source_code_verified_status, processing_status) 
                VALUES (%s, %s, %s, 0, 2)
            """
            await cursor.execute(contract_sql, (tx_id, chain_id, contract_address))
            
            # 2. Обновляем статус транзакции
            tx_sql = """
                UPDATE evm_block_create_contract_transaction 
                SET processing_status = 2, discovered_at = CURRENT_TIMESTAMP 
                WHERE id = %s
            """
            await cursor.execute(tx_sql, (tx_id,))
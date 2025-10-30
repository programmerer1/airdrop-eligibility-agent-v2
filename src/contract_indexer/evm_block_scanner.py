import asyncio
import logging
from typing import Dict, Any, List, Tuple
import aiomysql

from ..db_class.repositories.evm_block_scanner_repository import EvmBlockScannerRepository
from ..providers.api_client_interface import AbstractAPIClient

logger = logging.getLogger(__name__)

class EvmBlockScanner:
    """
    EvmBlockScanner (Сканер Транзакций в Блоке)
    
    Отвечает за сканирование блоков (evm_block), которые еще не обработаны (status=0).
    """

    def __init__(self, 
                 repository: EvmBlockScannerRepository, 
                 api_client: AbstractAPIClient,
                 batch_size: int):
        """
        Инициализация сканера.
        
        :param repository: Экземпляр EvmBlockScannerRepository.
        :param api_client: Экземпляр клиента API (EtherscanAPIClient).
        :param batch_size: Кол-во блоков, обрабатываемых за один цикл.
        """
        self._repository = repository
        self._api = api_client
        self._batch_size = batch_size
        logger.info("EvmBlockScanner initialized.")

    async def run(self):
        """
        Главный метод запуска сканера.
        Обрабатывает пачку блоков: параллельные API запросы, 
        последовательная обработка БД внутри одной транзакции.
        """
        logger.info("EvmBlockScanner run started...")
        
        all_contract_txs_to_insert: List[Tuple[int, int, str]] = []
        processed_block_ids: List[int] = [] # ID блоков, которые нужно пометить как завершенные

        async with (await self._repository.pool).acquire() as conn:
            await conn.begin()
            try:
                # 1. Атомарно выбрать и заблокировать пачку блоков (status=0)
                blocks_to_scan = await self._repository.lock_and_get_unprocessed_blocks(conn, self._batch_size)
                
                if not blocks_to_scan:
                    logger.info("EvmBlockScanner: No unprocessed blocks found.")
                    await conn.commit() 
                    return

                logger.info(f"EvmBlockScanner: Processing {len(blocks_to_scan)} blocks...")
                block_ids_in_batch = [b['id'] for b in blocks_to_scan]
                processed_block_ids = block_ids_in_batch # Сохраняем ID для финального обновления

                # 2. Пометить их как "в обработке" (status=1)
                await self._repository.batch_update_block_status(conn, block_ids_in_batch, 1)
                
                # 3. Запустить ПАРАЛЛЕЛЬНО только API запросы
                api_tasks = [
                    self._api.get_block_by_number(b['evm_network_chain_id'], b['block_number']) 
                    for b in blocks_to_scan
                ]
                # Ожидаем завершения всех API запросов
                # return_exceptions=True, чтобы одна ошибка API не уронила всю пачку
                api_results = await asyncio.gather(*api_tasks, return_exceptions=True) 

                # 4. Обработать результаты API ПОСЛЕДОВАТЕЛЬНО
                for block_info, block_data in zip(blocks_to_scan, api_results):
                    block_id = block_info['id']
                    
                    # Если gather вернул ошибку для этого API-запроса
                    if isinstance(block_data, Exception):
                        logger.error(f"EvmBlockScanner: API Error processing block_id={block_id}. Error: {block_data}")
                        raise block_data # <--- Выбрасываем ошибку, чтобы откатить ВСЮ транзакцию
                    
                    chain_id = block_info['evm_network_chain_id']
                    
                    if not block_data or 'transactions' not in block_data:
                        logger.warning(f"EvmBlockScanner: No data or transactions found via API for block_id={block_id}. Marking completed.")
                        # Блок все равно будет помечен как завершенный в конце
                        continue 

                    # Поиск транзакций создания контрактов в данных блока
                    for tx in block_data['transactions']:
                        if tx.get('to') is None:
                            tx_hash = tx.get('hash')
                            if tx_hash:
                                all_contract_txs_to_insert.append((block_id, chain_id, tx_hash))

                # 5. Выполнить ОДНУ массовую вставку найденных транзакций
                if all_contract_txs_to_insert:
                    logger.info(f"EvmBlockScanner: Found {len(all_contract_txs_to_insert)} contract creation(s) in this batch.")
                    await self._repository.batch_insert_contract_txs(conn, all_contract_txs_to_insert)
                
                # 6. Массово пометить ВСЕ блоки этой пачки как завершенные (status=2)
                await self._repository.mark_blocks_as_completed_batch(conn, processed_block_ids)
                
                logger.info(f"EvmBlockScanner: Successfully processed batch of {len(blocks_to_scan)} blocks.")
                await conn.commit() # Коммитим всю транзакцию

            except Exception as e:
                # Откат транзакции при любой ошибке (API или БД)
                await conn.rollback() 
                logger.error(f"EvmBlockScanner: Failed to process block batch. Transaction rolled back. Error: {e}", exc_info=True)

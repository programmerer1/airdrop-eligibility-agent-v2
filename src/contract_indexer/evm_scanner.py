# src/contract_indexer/evm_scanner.py
import asyncio
import logging
from typing import Dict, Any, List, Tuple
import aiomysql

from ..db_class.repositories.evm_scanner_repository import EvmScannerRepository
from ..providers.api_client_interface import AbstractAPIClient

logger = logging.getLogger(__name__)

class EvmScanner:
    """
    EvmScanner (Сканер Блоков)
    
    Отвечает за обнаружение новых блоков в активных сетях (evm_network)
    и сохранение их в таблицу evm_block.
    """

    def __init__(self, 
                 repository: EvmScannerRepository, 
                 api_client: AbstractAPIClient,
                 catch_up_threshold: int,
                 catch_up_batch_size: int,
                 follow_batch_size: int):
        
        self._repository = repository
        self._api = api_client
        self._catch_up_threshold = catch_up_threshold
        self._catch_up_batch_size = catch_up_batch_size
        self._follow_batch_size = follow_batch_size
        logger.info("EvmScanner initialized.")

    async def run(self):
        # ... (код без изменений) ...
        logger.info("EvmScanner run started...")
        try:
            networks = await self._repository.get_active_networks_to_scan()
            if not networks:
                logger.info("EvmScanner: No active networks to scan.")
                return
            tasks = [self.process_network(network) for network in networks]
            await asyncio.gather(*tasks)
            logger.info("EvmScanner run finished.")
        except Exception as e:
            logger.error(f"EvmScanner: Unhandled exception in run(): {e}", exc_info=True)


    # --- ИЗМЕНЕНО: Логика транзакций полностью перестроена ---
    async def process_network(self, network: Dict[str, Any]):
        """
        Обрабатывает одну сеть: находит и сохраняет новые блоки.
        Транзакции теперь выполняются ПО ПАРТИЯМ (в _process_batch),
        а не одна на всю сеть.
        """
        chain_id = network['chain_id']
        logger.info(f"EvmScanner: Processing network chain_id={chain_id}.")
        
        last_saved_block: int | None = network.get('last_discovered_block_number')
        finality_depth: int = network.get('finality_depth', 10) 

        # 1. Блокируем сеть (маленькая, быстрая транзакция)
        async with (await self._repository.pool).acquire() as conn:
            await conn.begin()
            try:
                await self._repository.start_network_processing(conn, chain_id)
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error(f"EvmScanner [Chain {chain_id}]: FAILED TO LOCK network. Error: {e}")
                return # Не можем продолжить

        try:
            # 2. Расчет (A): Определить диапазон сканирования
            latest_block_on_chain = await self._api.get_latest_block_number(chain_id)
            safe_latest_block = latest_block_on_chain - finality_depth
            
            if last_saved_block is None:
                start_block = safe_latest_block
            else:
                start_block = last_saved_block + 1
                
            if start_block > safe_latest_block:
                logger.info(f"EvmScanner [Chain {chain_id}]: No new blocks to scan. (Start: {start_block}, Safe Head: {safe_latest_block})")
                # Выходим (статус 1 останется, но finish_network_processing в 'finally' его сбросит)
                return

            blocks_to_scan_count = (safe_latest_block - start_block) + 1
            logger.info(f"EvmScanner [Chain {chain_id}]: Scanning from {start_block} to {safe_latest_block} ({blocks_to_scan_count} blocks).")

            # 3. Выбор режима (B, C)
            batch_size = 0
            if blocks_to_scan_count > self._catch_up_threshold:
                logger.info(f"EvmScanner [Chain {chain_id}]: Entering 'Catch-up' mode.")
                batch_size = self._catch_up_batch_size
            else:
                logger.info(f"EvmScanner [Chain {chain_id}]: Entering 'Follow-the-Head' mode.")
                batch_size = self._follow_batch_size
            
            # 4. Цикл обработки партий
            for current_start_block in range(start_block, safe_latest_block + 1, batch_size):
                current_end_block = min(current_start_block + batch_size - 1, safe_latest_block)
                
                # --- Каждая партия выполняется в своей транзакции ---
                await self._process_batch(
                    chain_id, 
                    current_start_block, 
                    current_end_block
                )
                # --------------------------------------------------
            
            logger.info(f"EvmScanner [Chain {chain_id}]: Successfully processed and saved up to block {safe_latest_block}.")

        except Exception as e:
            # Если любая партия (_process_batch) или get_latest_block_number
            # выбросит исключение, мы попадаем сюда.
            logger.error(f"EvmScanner [Chain {chain_id}]: Failed to process network. Error: {e}", exc_info=True)
            # Статус (processing_status=1) будет сброшен в 'finally'

        finally:
            # 5. Разблокируем сеть (маленькая, быстрая транзакция)
            async with (await self._repository.pool).acquire() as conn:
                await conn.begin()
                try:
                    await self._repository.finish_network_processing(conn, chain_id)
                    await conn.commit()
                    logger.info(f"EvmScanner [Chain {chain_id}]: Network unlocked.")
                except Exception as e:
                    await conn.rollback()
                    logger.error(f"EvmScanner [Chain {chain_id}]: CRITICAL: FAILED TO UNLOCK network. Error: {e}")

    
    # --- НОВЫЙ МЕТОД: Обработка одной партии в транзакции ---
    async def _process_batch(self, chain_id: int, start_block: int, end_block: int):
        """
        Обрабатывает ОДНУ партию блоков (от start_block до end_block)
        внутри одной атомарной транзакции.
        """
        logger.debug(f"EvmScanner [Chain {chain_id}]: Processing batch {start_block}-{end_block}")
        
        async with (await self._repository.pool).acquire() as conn:
            await conn.begin()
            try:
                # 1. Получаем данные по API
                block_numbers = list(range(start_block, end_block + 1))
                tasks = [self._api.get_block_by_number(chain_id, num) for num in block_numbers]
                api_results = await asyncio.gather(*tasks)

                blocks_to_insert: List[Tuple[int, int, str]] = []
                for block_data in api_results:
                    if block_data and 'number' in block_data and 'hash' in block_data:
                        block_num = int(block_data['number'], 16)
                        block_hash = block_data['hash']
                        blocks_to_insert.append((chain_id, block_num, block_hash))
                    else:
                        logger.warning(f"EvmScanner [Chain {chain_id}]: Received invalid block data: {block_data}")
                
                # 2. Атомарно вставляем блоки И обновляем 'last_discovered_block_number'
                if blocks_to_insert:
                    await self._repository.batch_insert_blocks(conn, blocks_to_insert)
                
                # Мы обновляем last_discovered_block_number до end_block,
                # даже если некоторые блоки были пропущены (invalid data)
                await self._repository.update_network_last_block(conn, chain_id, end_block)

                # 3. Коммитим транзакцию
                await conn.commit()
                logger.info(f"EvmScanner [Chain {chain_id}]: Committed batch {start_block}-{end_block}.")

            except Exception as e:
                # Откатываем транзакцию этой партии
                await conn.rollback()
                logger.error(f"EvmScanner [Chain {chain_id}]: Failed to process batch {start_block}-{end_block}. Transaction rolled back. Error: {e}")
                # Выбрасываем исключение выше, чтобы process_network остановил цикл
                raise
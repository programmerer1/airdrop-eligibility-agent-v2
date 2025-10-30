import asyncio
import logging
from typing import Dict, Any
import aiomysql
import json  

from ..db_class.repositories.evm_transaction_scanner_repository import EvmTransactionScannerRepository
from ..providers.api_client_interface import AbstractAPIClient

logger = logging.getLogger(__name__)

class EvmTransactionScanner:
    # ... (__init__ и run без изменений) ...
    def __init__(self, 
                 repository: EvmTransactionScannerRepository, 
                 api_client: AbstractAPIClient,
                 batch_size: int):
        self._repository = repository
        self._api = api_client
        self._batch_size = batch_size
        logger.info("EvmTransactionScanner initialized.")

    async def run(self):
        logger.info("EvmTransactionScanner run started...")
        async with (await self._repository.pool).acquire() as conn:
            await conn.begin()
            try:
                txs_to_scan = await self._repository.lock_and_get_unprocessed_txs(conn, self._batch_size)
                if not txs_to_scan:
                    logger.info("EvmTransactionScanner: No unprocessed contract transactions found.")
                    await conn.commit()
                    return
                logger.info(f"EvmTransactionScanner: Processing {len(txs_to_scan)} transactions...")
                tx_ids = [tx['id'] for tx in txs_to_scan]
                await self._repository.batch_update_tx_status(conn, tx_ids, 1)
                tasks = [self._process_transaction(conn, tx) for tx in txs_to_scan]
                await asyncio.gather(*tasks)
                logger.info(f"EvmTransactionScanner: Successfully processed batch of {len(txs_to_scan)} transactions.")
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error(f"EvmTransactionScanner: Failed to process transaction batch. Transaction rolled back. Error: {e}", exc_info=True)


    async def _process_transaction(self, conn: aiomysql.Connection, tx: Dict[str, Any]):
        tx_id = tx['id']
        chain_id = tx['evm_network_chain_id']
        tx_hash = tx['transaction_hash']
        logger.debug(f"EvmTransactionScanner: Processing tx_id={tx_id} (Hash: {tx_hash})")

        receipt = await self._api.get_transaction_receipt(chain_id, tx_hash)
        if not receipt or not receipt.get('contractAddress'):
            logger.warning(f"EvmTransactionScanner: Could not find contractAddress for tx_hash={tx_hash}. Marking as failed (status=2).")
            await self._repository.batch_update_tx_status(conn, [tx_id], 2)
            return
            
        contract_address = receipt['contractAddress']
        source_data = await self._api.get_contract_source(chain_id, contract_address)

        if not source_data:
             logger.warning(f"EvmTransactionScanner: API call getsourcecode returned no data for {contract_address}.")
             await self._repository.save_unverified_contract(conn, tx_id, chain_id, contract_address)
             return

        source_code_original = source_data.get('SourceCode')
        abi = source_data.get('ABI')
        contract_name = source_data.get('ContractName')

        is_verified = bool(source_code_original and source_code_original.strip())

        if is_verified:
            logger.info(f"EvmTransactionScanner: Found VERIFIED contract {contract_address} (tx_id={tx_id}).")
            
            source_code_to_save = "" # Инициализация
            cleaned_code = source_code_original.strip()

            # --- ИЗМЕНЕНИЕ: Строгая логика сохранения ---
            is_json_format = False
            # 1. Проверяем на формат Etherscan {{...}}
            if cleaned_code.startswith('{{') and cleaned_code.endswith('}}'):
                 potential_json_str = cleaned_code[1:-1]
                 try:
                     # Пытаемся распарсить внутренний JSON
                     json.loads(potential_json_str)
                     # Успех! Сохраняем очищенный JSON "как есть"
                     source_code_to_save = potential_json_str
                     is_json_format = True
                     logger.debug(f"Contract {contract_address}: Saved as cleaned Etherscan multi-file JSON.")
                 except json.JSONDecodeError as e:
                     # Ошибка парсинга внутреннего JSON! Вызываем исключение.
                     logger.error(f"Contract {contract_address}: Invalid JSON inside Etherscan {{...}} format. Error: {e}")
                     # Выбрасываем ошибку, чтобы откатить транзакцию
                     raise ValueError(f"Invalid JSON inside Etherscan {{...}} format for {contract_address}") from e

            # 2. Если не {{...}}, проверяем на обычный JSON { ... }
            elif not is_json_format and cleaned_code.startswith('{'):
                try:
                    json.loads(cleaned_code)
                    # Успех! Это валидный JSON, сохраняем "как есть"
                    source_code_to_save = cleaned_code
                    is_json_format = True
                    logger.debug(f"Contract {contract_address}: Saved as standard multi-file JSON.")
                except json.JSONDecodeError as e:
                    # Это НЕ валидный JSON, хотя и начинается с '{'. Считаем ошибкой.
                    logger.error(f"Contract {contract_address}: Invalid JSON detected (starts with '{{'). Error: {e}")
                    raise ValueError(f"Invalid JSON detected for {contract_address}") from e
                    
            # 3. Если это не JSON - считаем, что это обычный текст (однофайловый)
            if not is_json_format:
                 logger.debug(f"Contract {contract_address}: Saved as single-file source code wrapped in JSON.")
                 source_code_to_save = json.dumps({"source": cleaned_code})
            # --- Конец изменения ---

            await self._repository.save_contract_and_source(
                conn, 
                tx_id, 
                chain_id, 
                contract_address, 
                contract_name,
                source_code_to_save, # Сохраняем либо чистый JSON, либо {"source": ...}
                abi
            )
            
        else:
            logger.info(f"EvmTransactionScanner: Found UNVERIFIED contract {contract_address} (tx_id={tx_id}).")
            await self._repository.save_unverified_contract(
                conn, tx_id, chain_id, contract_address
            )
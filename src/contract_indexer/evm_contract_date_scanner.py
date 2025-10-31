import asyncio
import logging
import json
import time
from typing import Dict, Any, List
import aiomysql

from ..db_class.repositories.evm_contract_date_scanner_repository import EvmContractDateScannerRepository
from ..providers.api_client_interface import AbstractAPIClient
from ..utils.contract_utils import get_function_selector, decode_timestamp_from_eth_call, is_code_empty
from .. import services 

logger = logging.getLogger(__name__)

class EvmContractDateScanner:
    """
    Сканер дат Airdrop контрактов.
    Выполняет 4 задачи последовательно:
    1. Деактивирует истекшие контракты (по `claim_end_timestamp`).
    2. Деактивирует уничтоженные контракты (по `eth_getCode`).
    3. Запрашивает `claim_end_timestamp` по ABI.
    4. Запрашивает `claim_start_timestamp` по ABI.
    """
    def __init__(self,
                 repository: EvmContractDateScannerRepository,
                 batch_size: int):
        
        self._repository = repository
        self._batch_size = batch_size
        self._api: AbstractAPIClient = services.api_client_get_token 
        logger.info("EvmContractDateScanner initialized.")
        
    async def run(self):
        """
        Главный метод запуска сканера.
        """
        logger.info("EvmContractDateScanner run started...")
        
        # --- ШАГ 1: Быстрая деактивация истекших контрактов ---
        try:
            deactivated_count = await self._repository.deactivate_expired_contracts()
            if deactivated_count > 0:
                logger.info(f"Deactivated {deactivated_count} expired airdrop contracts.")
        except Exception as e:
            logger.error(f"Failed to deactivate expired contracts (Step 1): {e}", exc_info=True)
        
        # --- ШАГ 2: Деактивация уничтоженных контрактов (eth_getCode) ---
        await self._deactivate_destroyed_contracts()
        
        # --- ШАГ 3: Проверка claim_end_timestamp ---
        await self._process_claim_timestamp_check(
            check_type="claim_end",
            getter_method=self._repository.get_contracts_for_claim_end_check,
            abi_key='claim_end_getter_abi',
            update_method=self._repository.update_claim_end_timestamp,
            invalidate_method=self._repository.invalidate_claim_end_abi
        )
        
        # --- ШАГ 4: Проверка claim_start_timestamp ---
        await self._process_claim_timestamp_check(
            check_type="claim_start",
            getter_method=self._repository.get_contracts_for_claim_start_check,
            abi_key='claim_start_getter_abi',
            update_method=self._repository.update_claim_start_timestamp,
            invalidate_method=self._repository.invalidate_claim_start_abi
        )
        
        logger.info("EvmContractDateScanner run finished.")

    async def _deactivate_destroyed_contracts(self):
        """
        ШАГ 2: Проверяет `eth_getCode` для контрактов.
        """
        logger.debug("Running check for destroyed contracts (eth_getCode)...")
        contracts_to_check: List[Dict[str, Any]] = []
        conn = None 
        
        try:
            # 1. Получаем соединение и начинаем транзакцию
            conn = await (await self._repository.pool).acquire()
            await conn.begin()
            
            # 2. Выбираем пачку
            contracts_to_check = await self._repository.get_contracts_for_code_check(conn, self._batch_size)
            if not contracts_to_check:
                logger.debug("No contracts found for eth_getCode check.")
                await conn.commit()
                conn.close() # Закрываем соединение
                return

            logger.info(f"Checking eth_getCode for {len(contracts_to_check)} contracts...")

            # 3. Готовим API-задачи
            tasks = {
                c['id']: self._api.eth_getCode(c['evm_network_chain_id'], c['contract_address'])
                for c in contracts_to_check
            }
            
            # 4. Временно отпускаем соединение (но не коммитим), чтобы выполнить API-запросы
            conn.close() 
            conn = None

            # 5. ПАРАЛЛЕЛЬНО: Выполняем eth_getCode (БЕЗ активного 'conn')
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            results_map = dict(zip(tasks.keys(), results))

            dead_contract_ids = []

            # 6. ПОСЛЕДОВАТЕЛЬНО: Разбираем результаты
            for contract_id, code_result in results_map.items():
                if isinstance(code_result, Exception):
                    logger.error(f"API Error checking eth_getCode for id={contract_id}: {code_result}")
                    continue 
                
                if is_code_empty(code_result):
                    logger.info(f"Contract id={contract_id} is destroyed (eth_getCode result: {code_result}). Deactivating.")
                    dead_contract_ids.append(contract_id)
            
            # 7. Снова берем соединение и коммитим ИЗМЕНЕНИЯ В БД
            if dead_contract_ids:
                logger.info(f"Deactivating {len(dead_contract_ids)} destroyed contracts...")
                async with (await self._repository.pool).acquire() as conn_commit:
                    await conn_commit.begin()
                    try:
                        await self._repository.deactivate_contract_batch(conn_commit, dead_contract_ids)
                        await conn_commit.commit()
                    except Exception as commit_e:
                        await conn_commit.rollback()
                        logger.error(f"Failed to commit deactivated contracts: {commit_e}")
                        raise

        except Exception as e:
            # Откат при ЛЮБОЙ ошибке (включая ошибку `readexactly` при `conn.begin`)
            if conn and not conn.closed:
                try: await conn.rollback()
                except Exception as rb_e: logger.error(f"Failed to rollback transaction: {rb_e}")
            logger.error(f"Failed to process eth_getCode check batch. Transaction rolled back. Error: {e}", exc_info=True)
        finally:
            # Гарантированно закрываем соединение, если оно еще открыто
            if conn and not conn.closed:
                conn.close()

    async def _process_claim_timestamp_check(self, 
                                             check_type: str, 
                                             getter_method, 
                                             abi_key: str, 
                                             update_method, 
                                             invalidate_method):
        """
        Универсальный обработчик для Шагов 3 и 4.
        """
        logger.debug(f"Running check for: {check_type}")
        contracts_to_check: List[Dict[str, Any]] = []
        conn = None
        
        try:
            # 1. Получаем соединение и начинаем транзакцию
            conn = await (await self._repository.pool).acquire()
            await conn.begin()
            
            # 2. Выбрать пачку
            contracts_to_check = await getter_method(conn, self._batch_size)
            if not contracts_to_check:
                logger.debug(f"No contracts found for {check_type} check.")
                await conn.commit()
                conn.close()
                return

            logger.info(f"Checking {check_type} for {len(contracts_to_check)} contracts...")

            # 3. Подготовить API-задачи
            api_tasks = []
            contracts_map = []
            
            # (Этот цикл for безопасен, он делает DB-запросы последовательно)
            for contract in contracts_to_check:
                abi_json = contract.get(abi_key)
                try:
                    abi_data = json.loads(abi_json)
                    selector = get_function_selector(abi_data)
                    if selector:
                        api_tasks.append(self._api.eth_call(
                            contract['evm_network_chain_id'],
                            contract['contract_address'],
                            selector
                        ))
                        contracts_map.append(contract)
                    else:
                        await invalidate_method(conn, contract['id'])
                except (json.JSONDecodeError, TypeError):
                         await invalidate_method(conn, contract['id'])
            
            # 4. Временно отпускаем соединение
            conn.close()
            conn = None
            
            # 5. Выполняем API-задачи (БЕЗ активного 'conn')
            api_results = await asyncio.gather(*api_tasks, return_exceptions=True)

            # 6. Снова берем соединение и коммитим изменения
            async with (await self._repository.pool).acquire() as conn_commit:
                 await conn_commit.begin()
                 try:
                    current_time = int(time.time())
                    for contract, result in zip(contracts_map, api_results):
                        contract_id = contract['id']
                        
                        if isinstance(result, Exception):
                            logger.error(f"API Error checking {check_type} for id={contract_id}: {result}")
                            continue 
                        
                        timestamp = decode_timestamp_from_eth_call(result)
                        
                        if timestamp is None or timestamp == 0:
                            logger.warning(f"Invalid timestamp format returned for {check_type} (id={contract_id}). Result: {result}. Invalidating ABI.")
                            await invalidate_method(conn_commit, contract_id)
                        else:
                            if check_type == "claim_start":
                                logger.info(f"Found valid claim_start_timestamp {timestamp} for id={contract_id}.")
                                await update_method(conn_commit, contract_id, timestamp)
                            
                            elif check_type == "claim_end":
                                active_status = 1
                                if timestamp <= current_time:
                                    active_status = 0
                                    logger.info(f"Contract id={contract_id} is now INACTIVE (claim_end_timestamp {timestamp} <= now {current_time}).")
                                logger.info(f"Found valid claim_end_timestamp {timestamp} for id={contract_id}.")
                                await update_method(conn_commit, contract_id, timestamp, active_status)

                    await conn_commit.commit()
                 except Exception as commit_e:
                     await conn_commit.rollback()
                     logger.error(f"Failed to commit {check_type} check batch: {commit_e}")
                     raise

        except Exception as e:
            if conn and not conn.closed:
                try: await conn.rollback()
                except Exception as rb_e: logger.error(f"Failed to rollback transaction: {rb_e}")
            logger.error(f"Failed to process {check_type} check batch. Transaction rolled back. Error: {e}", exc_info=True)
        finally:
            if conn and not conn.closed:
                conn.close()
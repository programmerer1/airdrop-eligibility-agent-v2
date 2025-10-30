# src/contract_indexer/evm_contract_source_scanner.py
import asyncio
import logging
import json
from typing import Dict, Any, Optional
import aiomysql

from ..db_class.repositories.evm_contract_source_scanner_repository import EvmContractSourceScannerRepository
from ..utils.abi_filter import AirdropABIFilter
from ..utils.slither_analyzer import SlitherAnalyzer
from ..utils.llm_airdrop_analyzer import LLMAirdropAnalyzer
from .. import services 
from ..utils.contract_utils import get_function_selector, decode_address_from_eth_call
from ..providers.moralis_api_client import MoralisAPIError 

logger = logging.getLogger(__name__)

class EvmContractSourceScanner:
    """
    Сканер исходного кода контрактов (evm_contract_source).
    Выполняет 5-этапный анализ.
    """
    def __init__(self,
                 repository: EvmContractSourceScannerRepository,
                 abi_filter: AirdropABIFilter,
                 slither_analyzer: SlitherAnalyzer,
                 llm_analyzer: LLMAirdropAnalyzer,
                 batch_size: int):
        
        self._repository = repository
        self._abi_filter = abi_filter
        self._slither = slither_analyzer
        self._llm_analyzer = llm_analyzer
        self._batch_size = batch_size
        self._eth_call_client = services.api_client_get_token 
        self._token_metadata_client = services.api_client_token_metadata
        logger.info("EvmContractSourceScanner initialized.")
        
    async def run(self):
        # ... (код без изменений) ...
        logger.info("EvmContractSourceScanner run started...")
        async with (await self._repository.pool).acquire() as conn:
            await conn.begin()
            try:
                sources_to_scan = await self._repository.lock_and_get_unprocessed_sources(conn, self._batch_size)
                if not sources_to_scan:
                    logger.info("EvmContractSourceScanner: No new contract sources found for analysis.")
                    await conn.commit()
                    return
                logger.info(f"EvmContractSourceScanner: Processing {len(sources_to_scan)} contract sources...")
                source_ids = [s['id'] for s in sources_to_scan]
                await self._repository.batch_update_source_processing_status(conn, source_ids, 1)
                tasks = [self._process_source(conn, source) for source in sources_to_scan]
                await asyncio.gather(*tasks)
                logger.info(f"EvmContractSourceScanner: Successfully processed batch of {len(sources_to_scan)} sources.")
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error(f"EvmContractSourceScanner: Failed to process source batch. Transaction rolled back. Error: {e}", exc_info=True)


    async def _process_source(self, conn: aiomysql.Connection, source: Dict[str, Any]):
        """
        Выполняет полный 5-этапный анализ одного исходного кода.
        """
        source_id = source['id']
        contract_address = source['contract_address']
        chain_id = source['evm_network_chain_id'] 
        logger.debug(f"Analyzing source_id={source_id} (Address: {contract_address})")
        
        # --- ЭТАП 1: Быстрый ABI-фильтр ---
        is_airdrop_candidate = self._abi_filter.check_abi(source['abi'])
        if not is_airdrop_candidate:
            logger.info(f"Source_id={source_id}: Filtered out by ABI whitelist.")
            await self._repository.batch_update_source_processing_status(conn, [source_id], 2)
            return

        logger.debug(f"Source_id={source_id}: Passed ABI filter. Running Slither...")

        # --- ЭТАП 2: Анализ Slither ---
        slither_report_json = await self._slither.analyze_source_code(source['source_code'])
        if not slither_report_json:
            logger.error(f"Slither returned no report for source_id={source_id}. Rolling back.")
            raise ValueError(f"Slither returned no report for source_id={source_id}")
            
        (security_status, slither_report_str) = self._slither.classify_slither_report(slither_report_json)
        # Сохраняем отчет Slither в evm_contract_source
        await self._repository.save_slither_report(conn, source_id, security_status, slither_report_str)
        
        # --- ЭТАП 3: Анализ LLM (Только для "безопасных") ---
        if security_status not in [4, 5]: 
            logger.info(f"Source_id={source_id}: Skipping LLM analysis due to Slither status: {security_status}.")
            await self._repository.batch_update_source_processing_status(conn, [source_id], 2)
            return 

        logger.debug(f"Source_id={source_id}: Passed Slither (status={security_status}). Running LLM analysis...")
        llm_result = await self._llm_analyzer.analyze_contract(source['source_code'], source['abi'])
        
        if not llm_result:
            logger.info(f"Source_id={source_id}: LLM analysis determined this is NOT a valid airdrop contract.")
            await self._repository.batch_update_source_processing_status(conn, [source_id], 2)
            return

        # --- ЭТАП 4: Получение адреса токена (eth_call) ---
        token_address = llm_result.get('token_address')
        
        if not token_address and llm_result.get('get_token_function_abi'):
            logger.debug(f"Source_id={source_id}: Attempting to get token address via eth_call.")
            token_func_abi = llm_result['get_token_function_abi']
            func_selector = get_function_selector(token_func_abi)
            
            if func_selector:
                call_result = await self._eth_call_client.eth_call(chain_id, contract_address, func_selector) 
                if call_result:
                    found_token_address = decode_address_from_eth_call(call_result)
                    if found_token_address:
                        logger.info(f"Source_id={source_id}: Successfully obtained token address via eth_call: {found_token_address}")
                        token_address = found_token_address 
                        llm_result['token_address'] = token_address 
                    else:
                        logger.warning(f"Source_id={source_id}: Failed to decode address from eth_call result: {call_result}")
                else:
                    logger.warning(f"Source_id={source_id}: eth_call for get_token_function failed or returned empty.")
            else:
                logger.warning(f"Source_id={source_id}: Failed to generate selector for get_token_function_abi: {token_func_abi}")
        
        # --- ЭТАП 5: Получение метаданных токена ---
        token_metadata: Optional[Dict[str, Any]] = None 
        if token_address: 
            logger.debug(f"Source_id={source_id}: Attempting to get token metadata from provider for address: {token_address}")
            token_metadata = await self._token_metadata_client.get_token_metadata(
                chain_id=chain_id,
                token_address=token_address
            )
                 
        else:
             logger.warning(f"Source_id={source_id}: Skipping token metadata fetch because token_address is missing.")

        # --- ЭТАП 6: Сохранение результата Airdrop ---
        logger.info(f"Source_id={source_id}: SUCCESS! Found Airdrop contract. Saving to DB.")
        
        await self._repository.save_airdrop_contract(
            conn, 
            source, 
            llm_result, 
            token_metadata
        )
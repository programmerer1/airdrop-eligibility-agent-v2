import asyncio
import logging
import json
from typing import Dict, Any, Optional
import aiomysql

from ..db_class.repositories.evm_token_scanner_repository import EvmTokenScannerRepository
from ..utils.slither_analyzer import SlitherAnalyzer
from ..providers.api_client_interface import AbstractAPIClient

logger = logging.getLogger(__name__)

class EvmTokenScanner:
    def __init__(self,
                 repository: EvmTokenScannerRepository,
                 api_client: AbstractAPIClient,
                 slither_analyzer: SlitherAnalyzer,
                 batch_size: int):
        self._repository = repository
        self._slither = slither_analyzer
        self._batch_size = batch_size
        self._api = api_client
        logger.info("EvmTokenScanner initialized.")

    async def run(self):
        logger.info("EvmTokenScanner run started...")
        async with (await self._repository.pool).acquire() as conn:
            await conn.begin()
            try:
                tokens_to_scan = await self._repository.get_not_verified_token_data(conn, self._batch_size)
                if not tokens_to_scan:
                    logger.info("EvmTokenScanner: No new token found for analysis.")
                    await conn.commit()
                    return
                logger.info(f"EvmTokenScanner: Processing {len(tokens_to_scan)} tokens...")
                tasks = [self._process_token(conn, token) for token in tokens_to_scan]
                await asyncio.gather(*tasks)
                logger.info(f"EvmTokenScanner: Successfully processed of {len(tokens_to_scan)} tokens.")
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error(f"EvmTokenScanner: Failed to process tokens batch. Transaction rolled back. Error: {e}", exc_info=True)

    async def _process_token(self, conn: aiomysql.Connection, token: Dict[str, Any]):
        token_data_id = token['id']
        token_address = token['token_address']
        chain_id = token['evm_network_chain_id']
        token_security_report = json.loads(token['token_security_report'] or '[]')
        logger.debug(f"Analyzing token_data_id={token_data_id} (Address: {token_address})")
        source_data = await self._api.get_contract_source(chain_id, token_address)

        if not source_data:
            logger.warning(f"EvmTokenScanner: API call getsourcecode returned no data for {token_address}.")
            return
        
        source_code_original = source_data.get('SourceCode')
        is_verified = bool(source_code_original and source_code_original.strip())

        if is_verified:
            logger.info(f"EvmTokenScanner: Found VERIFIED contract {token_address} (token_data_id={token_data_id}).")

            source_code = ""
            cleaned_code = source_code_original.strip()

            is_json_format = False
            # 1. Проверяем на формат Etherscan {{...}}
            if cleaned_code.startswith('{{') and cleaned_code.endswith('}}'):
                 potential_json_str = cleaned_code[1:-1]
                 try:
                     json.loads(potential_json_str)
                     source_code = potential_json_str
                     is_json_format = True
                     logger.debug(f"EvmTokenScanner: Contract {token_address}: Saved as cleaned Etherscan multi-file JSON.")
                 except json.JSONDecodeError as e:
                     # Ошибка парсинга внутреннего JSON! Вызываем исключение.
                     logger.error(f"EvmTokenScanner: Contract {token_address}: Invalid JSON inside Etherscan {{...}} format. Error: {e}")
                     # Выбрасываем ошибку, чтобы откатить транзакцию
                     raise ValueError(f"EvmTokenScanner: Invalid JSON inside Etherscan {{...}} format for {token_address}") from e

            # 2. Если не {{...}}, проверяем на обычный JSON { ... }
            elif not is_json_format and cleaned_code.startswith('{'):
                try:
                    json.loads(cleaned_code)
                    source_code = cleaned_code
                    is_json_format = True
                    logger.debug(f"EvmTokenScanner: Contract {token_address}: Saved as standard multi-file JSON.")
                except json.JSONDecodeError as e:
                    # Это НЕ валидный JSON, хотя и начинается с '{'. Считаем ошибкой.
                    logger.error(f"EvmTokenScanner: Contract {token_address}: Invalid JSON detected (starts with '{{'). Error: {e}")
                    raise ValueError(f"EvmTokenScanner: Invalid JSON detected for {token_address}") from e
                    
            # 3. Если это не JSON - считаем, что это обычный текст (однофайловый)
            if not is_json_format:
                 logger.debug(f"EvmTokenScanner: Contract {token_address}: Saved as single-file source code wrapped in JSON.")
                 source_code = json.dumps({"source": cleaned_code})

            # --- Анализ Slither ---
            slither_report_json = await self._slither.analyze_source_code(source_code)
            if not slither_report_json:
                logger.error(f"EvmTokenScanner: Slither returned no report for token_data_id={token_data_id}. Rolling back.")
                raise ValueError(f"EvmTokenScanner: Slither returned no report for token_data_id={token_data_id}")

            (security_status, slither_report_str) = self._slither.classify_slither_report(slither_report_json)

            token_security_report.append(
                {
                "error": slither_report_json.get('error', ""),
                "results": slither_report_json.get('results', {}),
                "success": slither_report_json.get('success', False),
                "provider": "Slither"
                }
            )
            
            await self._repository.update_token_analysis_status(
                conn,
                token_data_id,
                security_status,
                json.dumps(token_security_report)
            )

        else:
            logger.info(f"EvmTokenScanner: Found UNVERIFIED contract {token_address} (token_data_id={token_data_id}).")
        
import logging
import json
import time
from typing import List, Dict, Any, Optional
import aiomysql
from ..base_repository import BaseRepository

logger = logging.getLogger(__name__)

class EvmContractSourceScannerRepository(BaseRepository):
    """
    Репозиторий для EvmContractSourceScanner.
    """

    async def lock_and_get_unprocessed_sources(self, conn: aiomysql.Connection, batch_size: int) -> List[Dict[str, Any]]:
        sql = """
            SELECT cs.id, cs.evm_network_chain_id, cs.contract_address, 
                   cs.contract_name, cs.source_code, cs.abi
            FROM evm_contract_source AS cs
            WHERE cs.processing_status = 0 AND cs.security_analysis_status = 0
            LIMIT %s FOR UPDATE SKIP LOCKED
        """
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, (batch_size,))
            return await cursor.fetchall()


    async def batch_update_source_processing_status(self, conn: aiomysql.Connection, source_ids: List[int], status: int):
        if not source_ids: return

        format_strings = ','.join(['%s'] * len(source_ids))
        sql = f"UPDATE evm_contract_source SET processing_status = %s WHERE id IN ({format_strings})"
        
        params = (status, *source_ids)
        
        async with conn.cursor() as cursor:
            await cursor.execute(sql, params)

    async def save_slither_report(self, conn: aiomysql.Connection, 
                                  source_id: int, 
                                  security_status: int, 
                                  report_json: str):
        sql = """
            UPDATE evm_contract_source 
            SET security_analysis_status = %s, 
                security_analysis_report = %s
            WHERE id = %s
        """
        try:
            json.loads(report_json)
            async with conn.cursor() as cursor:
                await cursor.execute(sql, (security_status, report_json, source_id))
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON format for Slither report (source_id={source_id}). Skipping report update.")
            sql_no_report = "UPDATE evm_contract_source SET security_analysis_status = %s WHERE id = %s"
            async with conn.cursor() as cursor:
                await cursor.execute(sql_no_report, (security_status, source_id))
        except Exception as e:
            logger.error(f"Failed to save slither report for source_id={source_id}: {e}", exc_info=True)
            raise

    def _parse_llm_time_field(self, value: Any) -> tuple:
        if value is None: return (None, None)
        if isinstance(value, (int, float)): return (None, int(value))
        if isinstance(value, (dict, list)):
            try: return (json.dumps(value), None)
            except TypeError: return (None, None)
        if isinstance(value, str):
            try: return (None, int(value))
            except ValueError:
                try: json.loads(value); return (value, None)
                except json.JSONDecodeError: return (None, None)
        return (None, None)

    async def save_airdrop_contract(self, conn: aiomysql.Connection, 
                                    source_data: Dict[str, Any], 
                                    llm_result: Dict[str, Any],
                                    token_metadata: Optional[Dict[str, Any]]):
        """
        Атомарно сохраняет финальный результат в 'evm_airdrop_eligibility_contract'
        и помечает 'evm_contract_source' как завершенный.
        """
        
        # 1. Подготовка данных для вставки
        source_id = source_data['id']
        chain_id = source_data['evm_network_chain_id']
        contract_address = source_data['contract_address']
        contract_name = source_data.get('contract_name') 

        eligibility_abi = json.dumps(llm_result['eligibility_function_abi'])
        (start_abi, start_ts) = self._parse_llm_time_field(llm_result.get('claim_start_getter_abi'))
        (end_abi, end_ts) = self._parse_llm_time_field(llm_result.get('claim_end_getter_abi'))
        (get_token_abi, _) = self._parse_llm_time_field(llm_result.get('get_token_function_abi'))
        
        token_address = llm_result.get('token_address')
        token_ticker = llm_result.get('token_ticker')
        token_decimals = llm_result.get('token_decimals')

        token_analysis_status = 0
        active_status = 1
        security_reports_list = []
        
        # 2. Добавляем отчет о метаданных токена
        if token_metadata:
            if not token_ticker:
                token_ticker = token_metadata.get('symbol')
            if token_decimals is None: 
                decimals_str = token_metadata.get('decimals')
                try: token_decimals = int(decimals_str) if decimals_str is not None else 18
                except (ValueError, TypeError): token_decimals = 18

            provider_name = "TokenMetadataProvider(Moralis)"
            
            metadata_report = {
                "security_score": token_metadata.get('security_score'), 
                "possible_spam": token_metadata.get('possible_spam', False), 
                "verified_contract": token_metadata.get('verified_contract', False), 
                "provider": provider_name
            }
            security_reports_list.append(metadata_report)

            if metadata_report["possible_spam"] is True:
                active_status = 0 
                token_analysis_status = 2 # 2 = unsafe
                logger.warning(f"Contract source_id={source_id} marked as inactive due to possible_spam=true from metadata provider.")
        
        # Конвертируем массив (который содержит 0 или 1 элемент) в JSON
        token_security_report_json = json.dumps(security_reports_list)

        if active_status == 1 and end_ts and end_ts < int(time.time()):
            active_status = 0

        # Вставляем в evm_airdrop_eligibility_contract
        sql_insert = f"""
            INSERT INTO evm_airdrop_eligibility_contract
            (evm_network_chain_id, evm_contract_source_id, contract_address, 
             eligibility_function_abi, get_token_function_abi, 
             claim_start_getter_abi, claim_end_getter_abi,
             claim_start_timestamp, claim_end_timestamp, contract_name, 
             token_address, token_ticker, token_decimals, 
             token_analysis_status, token_security_report, 
             active_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, FROM_UNIXTIME(%s), FROM_UNIXTIME(%s), %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            chain_id, source_id, contract_address,
            eligibility_abi, get_token_abi, 
            start_abi, end_abi,
            start_ts,
            end_ts,
            contract_name,
            token_address, 
            token_ticker, 
            token_decimals, 
            token_analysis_status, 
            token_security_report_json, # <--- Здесь теперь массив только с отчетом Moralis (или пустой)
            active_status
        )

        async with conn.cursor() as cursor:
            try:
                await cursor.execute(sql_insert, params)
            except Exception as insert_err:
                 logger.error(f"Failed to insert into evm_airdrop_eligibility_contract for source_id={source_id}: {insert_err}")
                 raise insert_err
            
            # 3. Помечаем исходник (evm_contract_source) как завершенный
            sql_update = "UPDATE evm_contract_source SET processing_status = 2 WHERE id = %s"
            await cursor.execute(sql_update, (source_id,))
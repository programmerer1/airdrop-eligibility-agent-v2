import asyncio
import logging
import signal
from dotenv import load_dotenv

load_dotenv()

from . import config

from . import services

from .contract_indexer.evm_scanner import EvmScanner
from .contract_indexer.evm_block_scanner import EvmBlockScanner
from .contract_indexer.evm_transaction_scanner import EvmTransactionScanner
from .contract_indexer.evm_contract_source_scanner import EvmContractSourceScanner 
from .contract_indexer.evm_contract_date_scanner import EvmContractDateScanner

from .utils.abi_filter import AirdropABIFilter 
from .utils.slither_analyzer import SlitherAnalyzer 
from .utils.llm_airdrop_analyzer import LLMAirdropAnalyzer 

# Logging settings
if config.APP_ENV == 'prod':
    log_level = logging.WARNING # Only WARNING and ERROR
    log_level_name = 'WARNING'
else:
    # dev
    log_level = logging.INFO # INFO, WARNING, ERROR
    log_level_name = 'INFO'
logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.info(f"Logging level set to {log_level_name} based on APP_ENV='{config.APP_ENV}'")


# --- Инициализация Утилит Анализа ---
abi_filter = AirdropABIFilter(keywords=config.AIRDROP_ABI_KEYWORDS)
slither_analyzer = SlitherAnalyzer()
llm_analyzer = LLMAirdropAnalyzer(client=services.analyzer_api_client_llm)

# --- Инициализация Сканеров ---
evm_scanner = EvmScanner(
    repository=services.repo_evm,
    api_client=services.api_client_evm,
    catch_up_threshold=config.EVM_SCANNER_CATCH_UP_THRESHOLD,
    catch_up_batch_size=config.EVM_SCANNER_CATCH_UP_BATCH_SIZE,
    follow_batch_size=config.EVM_SCANNER_FOLLOW_BATCH_SIZE
)

block_scanner = EvmBlockScanner(
    repository=services.repo_block,
    api_client=services.api_client_block,
    batch_size=config.EVM_BLOCK_SCANNER_BATCH_SIZE
)

tx_scanner = EvmTransactionScanner(
    repository=services.repo_tx,
    api_client=services.api_client_tx,
    batch_size=config.EVM_TRANSACTION_SCANNER_BATCH_SIZE
)

source_scanner = EvmContractSourceScanner(
    repository=services.repo_source,
    abi_filter=abi_filter,
    slither_analyzer=slither_analyzer,
    llm_analyzer=llm_analyzer,
    batch_size=config.EVM_CONTRACT_SOURCE_SCANNER_BATCH_SIZE
)

date_scanner = EvmContractDateScanner(
    repository=services.repo_date_scanner,
    batch_size=config.EVM_CONTRACT_DATE_SCANNER_BATCH_SIZE
)

async def run_scanner_loop(scanner_name: str, scanner_instance, interval: int):
    """
    Обёртка-цикл (daemon-style) для запуска сканера с заданным интервалом.
    """
    logger.info(f"Starting scanner loop for {scanner_name} with interval {interval}s")
    while True:
        try:
            await scanner_instance.run()
        except Exception as e:
            logger.error(f"Error in {scanner_name} loop: {e}", exc_info=True)
        
        await asyncio.sleep(interval)


async def main():
    """
    Главная асинхронная функция.
    Инициализирует пул БД и запускает циклы сканеров.
    """
    try:
        logger.info("Initializing database pool...")
        # Используем импортированный коннектор
        await services.db_connector.init_pool() 
        logger.info("Database pool initialized.")
        
        tasks = [
            asyncio.create_task(run_scanner_loop(
                "EvmScanner", evm_scanner, config.EVM_SCANNER_RUN_INTERVAL
            )),
            asyncio.create_task(run_scanner_loop(
                "EvmBlockScanner", block_scanner, config.EVM_BLOCK_SCANNER_RUN_INTERVAL
            )),
            asyncio.create_task(run_scanner_loop(
                "EvmTransactionScanner", tx_scanner, config.EVM_TRANSACTION_SCANNER_RUN_INTERVAL
            )),
            asyncio.create_task(run_scanner_loop(
                "EvmContractSourceScanner", source_scanner, config.EVM_CONTRACT_SOURCE_SCANNER_RUN_INTERVAL
            )),
            asyncio.create_task(run_scanner_loop(
                "EvmContractDateScanner", date_scanner, config.EVM_CONTRACT_DATE_SCANNER_RUN_INTERVAL
            )),
        ]
        
        await asyncio.gather(*tasks)
        
    except asyncio.CancelledError:
        logger.info("Main task cancelled. Shutting down...")
    finally:
        logger.info("Closing database pool...")
        # Используем импортированный коннектор
        await services.db_connector.close_pool()
        logger.info("Shutdown complete.")


def handle_shutdown(sig, loop):
    """Обработчик сигналов (Ctrl+C) для корректного завершения."""
    logger.info(f"Received signal {sig}. Initiating graceful shutdown...")
    for task in asyncio.all_tasks(loop):
        task.cancel()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown, sig, loop)
        
    try:
        loop.run_until_complete(main())
    finally:
        logger.info("Application stopped.")
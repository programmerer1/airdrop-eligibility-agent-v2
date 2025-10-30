import asyncio
from . import config

from .providers.etherscan_api_client import EtherscanAPIClient
from .providers.openai_compatible_api_client import OpenAICompatibleClient
from .providers.moralis_api_client import MoralisAPIClient

from .db_class.mysql_connector import MySQLConnector

from .db_class.repositories.evm_scanner_repository import EvmScannerRepository
from .db_class.repositories.evm_block_scanner_repository import EvmBlockScannerRepository
from .db_class.repositories.evm_transaction_scanner_repository import EvmTransactionScannerRepository
from .db_class.repositories.evm_contract_source_scanner_repository import EvmContractSourceScannerRepository
from .db_class.repositories.evm_contract_date_scanner_repository import EvmContractDateScannerRepository

"""
This file acts as a Service Locator.
It creates SINGLE INSTANCES of all shared services.
Any other file in the application can import this file
and access already configured clients or repositories.
"""

# --- API blocks ---
agent_rate_limit_lock_etherscan = asyncio.Lock()
analyzer_api_rate_limit_lock_llm = asyncio.Lock()
api_rate_limit_lock_llm = asyncio.Lock()
api_rate_limit_lock_moralis = asyncio.Lock()

# --- Scanner locks (depending on mode) ---
if config.SCANNERS_API_PARALLEL_MODE:
    # PARALLEL MODE: Each client has its own independent lock.
    # This will allow 4 scanners to make requests simultaneously.
    lock_evm_scanner = asyncio.Lock()
    lock_block_scanner = asyncio.Lock()
    lock_tx_scanner = asyncio.Lock()
    lock_date_scanner = asyncio.Lock()
    lock_get_token = asyncio.Lock()
else:
    # SINGLE MODE (default): All clients share one lock
    # This will put all requests in a single queue.
    single_global_lock = asyncio.Lock()
    lock_evm_scanner = single_global_lock
    lock_block_scanner = single_global_lock
    lock_tx_scanner = single_global_lock
    lock_date_scanner = single_global_lock
    lock_get_token = single_global_lock

db_connector = MySQLConnector(minsize=1, maxsize=10, autocommit=False)

# --- Repositories (Use a single connector) ---
repo_evm = EvmScannerRepository(db_connector)
repo_block = EvmBlockScannerRepository(db_connector)
repo_tx = EvmTransactionScannerRepository(db_connector)
repo_source = EvmContractSourceScannerRepository(db_connector)
repo_date_scanner = EvmContractDateScannerRepository(db_connector)

# --- EvmScanner API client ---
api_client_evm = EtherscanAPIClient(
    base_url=config.EVM_SCANNER_API_URL,
    api_key=config.EVM_SCANNER_API_KEY,
    delay_seconds=config.EVM_API_REQUEST_DELAY,
    timeout=config.EVM_SCANNER_API_TIMEOUT,
    lock=lock_evm_scanner,
    proxy_url=config.EVM_SCANNER_API_PROXY_URL
)

# --- EvmBlockScanner API client ---
api_client_block = EtherscanAPIClient(
    base_url=config.EVM_BLOCK_SCANNER_API_URL,
    api_key=config.EVM_BLOCK_SCANNER_API_KEY,
    delay_seconds=config.EVM_API_REQUEST_DELAY,
    timeout=config.EVM_BLOCK_SCANNER_API_TIMEOUT,
    lock=lock_block_scanner,
    proxy_url=config.EVM_BLOCK_SCANNER_API_PROXY_URL
)

# --- EvmTransactionScanner API client ---
api_client_tx = EtherscanAPIClient(
    base_url=config.EVM_TRANSACTION_SCANNER_API_URL,
    api_key=config.EVM_TRANSACTION_SCANNER_API_KEY,
    delay_seconds=config.EVM_API_REQUEST_DELAY,
    timeout=config.EVM_TRANSACTION_SCANNER_API_TIMEOUT,
    lock=lock_tx_scanner,
    proxy_url=config.EVM_TRANSACTION_SCANNER_API_PROXY_URL
)

# --- EvmContractDateScanner API client ---
api_client_date_scanner = EtherscanAPIClient(
    base_url=config.EVM_CONTRACT_DATE_SCANNER_API_URL,
    api_key=config.EVM_CONTRACT_DATE_SCANNER_API_KEY,
    delay_seconds=config.EVM_API_REQUEST_DELAY,
    timeout=config.EVM_CONTRACT_DATE_SCANNER_API_TIMEOUT,
    lock=lock_date_scanner,
    proxy_url=config.EVM_CONTRACT_DATE_SCANNER_API_PROXY_URL
)

# ---  API client for fetching the token address ---
api_client_get_token = EtherscanAPIClient(
    base_url=config.EVM_GET_TOKEN_HASH_API_URL,
    api_key=config.EVM_GET_TOKEN_HASH_API_KEY,
    delay_seconds=config.EVM_API_REQUEST_DELAY, 
    timeout=config.EVM_GET_TOKEN_HASH_API_TIMEOUT,
    lock=lock_get_token,
    proxy_url=config.EVM_GET_TOKEN_HASH_API_PROXY_URL
)

# ---  API client for fetching the token metadata ---
api_client_token_metadata = MoralisAPIClient(
    base_url=config.EVM_GET_TOKEN_METADATA_API_URL,
    api_key=config.EVM_GET_TOKEN_METADATA_API_KEY,
    lock=api_rate_limit_lock_moralis, 
    timeout=config.EVM_GET_TOKEN_METADATA_API_TIMEOUT,
    proxy_url=config.EVM_GET_TOKEN_METADATA_API_PROXY_URL
)

# --- OpenAI (LLM) API client (for contract analysis) ---
analyzer_api_client_llm = OpenAICompatibleClient(
    base_url=config.CONTRACT_ANALYZER_MODEL_API_URL,
    api_key=config.CONTRACT_ANALYZER_MODEL_API_KEY,
    model=config.CONTRACT_ANALYZER_MODEL_NAME,
    lock=analyzer_api_rate_limit_lock_llm,
    timeout=config.CONTRACT_ANALYZER_MODEL_TIMEOUT,
    proxy_url=config.CONTRACT_ANALYZER_MODEL_API_PROXY_URL
)

# --- OpenAI (LLM) API client (for extracting user prompts) ---
extractor_client_llm = OpenAICompatibleClient(
    base_url=config.EXTRACTOR_MODEL_API_URL,
    api_key=config.EXTRACTOR_MODEL_API_KEY,
    model=config.EXTRACTOR_MODEL_NAME,
    lock=api_rate_limit_lock_llm,
    timeout=config.EXTRACTOR_MODEL_API_TIMEOUT,
    proxy_url=config.EXTRACTOR_MODEL_API_PROXY_URL
)

# --- OpenAI (LLM) API client (for generating final user responses) ---
response_formatter_client_llm = OpenAICompatibleClient(
    base_url=config.MODEL_API_URL,
    api_key=config.MODEL_API_KEY,
    model=config.MODEL_NAME,
    lock=api_rate_limit_lock_llm,
    timeout=config.MODEL_API_TIMEOUT,
    proxy_url=config.MODEL_API_PROXY_URL
)

# --- Agent API (For eth_call contract airdrop eligibility request) ---
agent_evm_api_client = EtherscanAPIClient(
    base_url=config.EVM_API_URL,
    api_key=config.EVM_API_KEY,
    delay_seconds=config.EVM_API_REQUEST_DELAY,
    timeout=config.EVM_API_TIMEOUT,
    lock=agent_rate_limit_lock_etherscan,
    proxy_url=config.EVM_API_PROXY_URL
)
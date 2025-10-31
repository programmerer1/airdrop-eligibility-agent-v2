# <p align="center">AECA (Airdrop Eligibility Checker Agent) V2</p>

<p align="center">
    <img src="https://github.com/programmerer1/airdrop-eligibility-agent-v2/blob/main/logo.jpeg" width="300" alt="logo">
</p>

This project is an automated system for the continuous scanning of EVM-compatible blockchain networks. Its primary task is to detect newly deployed smart contracts, conduct a deep analysis of them, and identify those intended for Airdrop distribution.

The system operates as an asynchronous, multi-stage pipeline. It consists of five independent services (scanners) that run in parallel. They exchange tasks and results through a shared MySQL database.

This is an updated version of another agent (Airdrop Eligibility Checker Agent) https://github.com/programmerer1/airdrop-eligibility-agent . While in the previous version, data for the checker was added manually to a yaml file, in the new version, the program scans EVM networks (specified in the `evm_network` table), analyzes, and saves the data.

The application is divided into two parts: Scanners and Agent.

The agent is developed based on the Sentient Agent Framework
https://github.com/sentient-agi/Sentient-Agent-Framework

---
## Scanner Lifecycle

The entire process, from block detection to final contract analysis, is divided into 5 stages, each performed by a separate service.

### 1. Block Scanner

* **Objective:** To find new, confirmed blocks on the networks.
* **Process:**
    1.  This service monitors active networks (e.g., Ethereum, Linea) specified in the database, in the `evm_network` table.
    2.  It queries the API for the latest block number.
    3.  To avoid blockchain reorganization (fork) issues, it steps back from the "tip" by a safe number of blocks (finalization depth).
    4.  New, confirmed blocks are written to the database as tasks for the next scanner.

### 2. Transaction Scanner

* **Objective:** To find transactions that created new contracts.
* **Process:**
    1.  This service takes the "raw" blocks found in the previous step.
    2.  It queries the API for the full content of each block, including the list of all transactions.
    3.  It analyzes this list and looks for a specific type of transaction: those with an indication of new contract creation.
* **Output:** The hashes of these "creation transactions" are saved to the database as tasks for the next stage.

### 3. Source Code Scanner

* **Objective:** To get the new contract's address and its source code.
* **Process:**
    1.  This service takes the "creation transactions" from the previous step.
    2.  It makes two API requests:
        * The first, to get its "receipt" by the transaction hash and find out the **address** of the created contract.
        * The second, to request its **verified source code** and **ABI** by the contract address.
    3.  If the code is obtained, it is formatted into a standard JSON view (even if it was a single file) for unified processing.
* **Output:** The source code, ABI, and contract name are saved to the database, forming a queue for the main analytical scanner.

### 4. Contract Analyzer

* **Objective:** To check the contract's source code for security and Airdrop logic.
* **Process:** This is the most complex stage, divided into several steps:
    1.  **Quick Filter (ABI):** First, the service quickly checks the contract's ABI. If it doesn't contain keywords from the whitelist, the contract is discarded as irrelevant.
    2.  **Security Analysis (Slither):** If the filter is passed, the code is run through `Slither`. It looks for vulnerabilities. The results (including compilation errors or dangerous findings) are saved in a security report.
    3.  **Logic Analysis (LLM):** If Slither finds no critical issues, the code and ABI are sent to a large language model (AI) with the task of finding specific functions responsible for checking Airdrop eligibility.
    4.  **Token Search (eth_call):** If the AI finds a function that *returns* a token address, the scanner makes an `eth_call` request to the blockchain to execute this function and get the address.
    5.  **Token Analysis:** If the token address is now known, the scanner queries an API (e.g., Moralis) to get the token's metadata: its ticker, decimals, and, most importantly, a security report (e.g., whether the token is spam).
* **Output:** If all checks are passed and the contract is identified as an Airdrop, all collected data (function ABIs, token address, ticker, spam report) are written to the **final results table**.

### 5. Date Scanner

* **Objective:** To maintain the relevance of the final Airdrop contracts table.
* **Process:** This service periodically performs 4 tasks:
    1.  **Deactivation by Date:** Finds contracts whose claim end date has passed and marks them as inactive.
    2.  **Search for "Dead" (eth_getCode):** Finds active contracts whose end date is not yet known. It makes an `eth_getCode` request. If the contract has been destroyed, the scanner marks it as inactive.
    3.  **Search for End Date:** For "live" contracts that have a function to get the end date (but the date itself is not yet known), the scanner makes an `eth_call` to get and record this date.
    4.  **Search for Start Date:** Does the same for the claim start date.

---
## Database Structure

The database is the "heart" of the pipeline. Each table (except `evm_network`) represents a task queue for the next scanner.

* **`evm_network`**
    * **Purpose:** Configuration table. Stores the list of networks to be scanned (ID, name) and their current state (which block was last).

* **`evm_block`**
    * **Purpose:** Queue for the Transaction Scanner.
    * **Contains:** Blocks awaiting checks for contract creation transactions.

* **`evm_block_create_contract_transaction`**
    * **Purpose:** Queue for the Source Code Scanner.
    * **Contains:** Hashes of transactions that created a contract and are awaiting source code download.

* **`evm_contract`**
    * **Purpose:** Registry of all found contract addresses. Links a transaction to an address.

* **`evm_contract_source`**
    * **Purpose:** Queue for the Airdrop Analyzer.
    * **Contains:** Source code (in JSON format), ABI, and security reports (Slither).

* **`evm_airdrop_eligibility_contract`**
    * **Purpose:** **Final result.** This is the data showcase, containing only identified Airdrop contracts.
    * **Contains:** All extracted information: ABIs of eligibility check functions, ABIs for getting dates, token addresses, tickers, token security reports, and activity status (is the Airdrop currently active).

* **`research_cache`**
    * **Purpose:** Caching table. Used by another part of the application (the agent), not the scanners.

**The ETH network is added by default**

If you want to add a network before launching:

Before launching the containers, you can add EVM networks for the scanners. To do this, you need to add the network in the `init.sql` file using the SQL INSERT command into the `evm_network` table. By default, the ETH Mainnet network is already added to the file.

You can also add a new network to the evm_network table at any time.

## Installation
Clone the repository (**You must configure the variables in the env files.**)
```bash
git clone https://github.com/programmerer1/airdrop-eligibility-agent-v2

cd airdrop-eligibility-agent-v2

cp .env.example .env
cp .mysql_env.example .mysql_env

mkdir db_data
docker compose -f docker-compose.yml up -d
```

## Description of the fields in the evm_network table:

- chain_id - EVM network identifier

- chain_name - EVM network name

- created_at - This field is automatically set when inserting a new record (Network)

- discovered_at - Time of the scanner's last interaction with this record (**For scanners only**)

- last_discovered_block_number - Number of the last block discovered by the scanner (**For scanners only**). **However, you can specify a block number when adding a new network to the database to indicate to the scanner which block to start scanning from in that network.**

- active_status - 0 - The scanner will not look for new blocks in this network, 1 - The scanner will look for blocks. **Default: 1**

- processing_status - 0 - Available for processing, 1 - The scanner has locked and is working with this network (**For scanners only**). **Default: 0**

- finality_depth - Protects against reorganizations (reorgs) by forcing EvmScanner to back off from the latest  network block. Logic: Safe_Block_For_Scanning = (Latest_Block_Via_API) - finality_depth. The scanner will only process blocks up to this "safe" number, ensuring that processed data won't "disappear" due to block reversal. **Default: 12**

Example POST request to localhost:8000/assist:
```json
{
    "session": 
    {
        "processor_id":"sentient-chat-client",
        "activity_id":"01K6BEMNWZFMP3RMGJTFZBND2N",
        "request_id": "01K6BEPKY12FMR1S19Y3SE01C6",
        "interactions":[]
    }, 
    "query": 
    {
        "id": "01K6BEMZ2QZQ58ADNDCKBPKD51", 
        "prompt": "Check my wallet 0x4abaf7b00248bcf38984477be31fa2aeca6ba1a8",
        "context": ""
    }
}
```
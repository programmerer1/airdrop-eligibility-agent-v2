CREATE TABLE IF NOT EXISTS evm_network (
    id SMALLINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    chain_id INT UNSIGNED NOT NULL UNIQUE,
    chain_name VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    discovered_at TIMESTAMP DEFAULT NULL COMMENT 'Date of last discovery/scan (updated only by scanner)',
    last_discovered_block_number BIGINT UNSIGNED DEFAULT NULL COMMENT 'The last block number that has been discovered. From this block + 1, the next query will begin.',
    active_status TINYINT NOT NULL DEFAULT 1 COMMENT '0 = inactive, 1 = active',
    processing_status TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0 = not started, 1 = processing',
    finality_depth SMALLINT UNSIGNED NOT NULL DEFAULT 12 COMMENT 'Finality depth. Protects against reorganizations (reorgs) by forcing EvmScanner to back off from the latest network block. Logic: Safe_Block_For_Scanning = (Latest_Block_Via_API) - finality_depth. The scanner will only process blocks up to this "safe" number, ensuring that processed data won\'t "disappear" due to block reversal.'
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS evm_block (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    evm_network_chain_id INT UNSIGNED NOT NULL,
    block_number BIGINT UNSIGNED NOT NULL COMMENT 'ATTENTION! Not a unique value. Different networks may have the same number.',
    block_hash CHAR(66) NOT NULL COMMENT 'ATTENTION! Not a unique value. Different networks may have the same hash.',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    discovered_at TIMESTAMP DEFAULT NULL COMMENT 'Date of last discovery/scan (updated only by scanner)',
    processing_status TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0 = not started, 1 = processing, 2 = completed',
    INDEX evm_block_processing_status (processing_status),
    UNIQUE KEY evm_network_block_number_unique_key (evm_network_chain_id, block_number),
    CONSTRAINT evm_network_evm_block_key FOREIGN KEY(evm_network_chain_id) REFERENCES evm_network(chain_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS evm_block_create_contract_transaction (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    evm_block_id BIGINT UNSIGNED NOT NULL,
    evm_network_chain_id INT UNSIGNED NOT NULL COMMENT 'Denormalization to avoid unnecessary JOINs with large data sets',
    transaction_hash CHAR(66) NOT NULL COMMENT 'ATTENTION! Not a unique value. Different networks may have the same hash.',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    discovered_at TIMESTAMP DEFAULT NULL COMMENT 'Date of last discovery/scan (updated only by scanner)',
    processing_status TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0 = not started, 1 = in progress, 2 = completed',
    INDEX evm_block_create_contract_transaction_processing_status (processing_status),
    UNIQUE KEY evm_block_transaction_hash_unique_key (evm_block_id, transaction_hash),
    CONSTRAINT evm_block_evm_block_transaction_key FOREIGN KEY(evm_block_id) REFERENCES evm_block(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT evm_network_evm_block_transaction_key FOREIGN KEY(evm_network_chain_id) REFERENCES evm_network(chain_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS evm_contract(
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    evm_block_create_contract_transaction_id BIGINT UNSIGNED NOT NULL,
    evm_network_chain_id INT UNSIGNED NOT NULL COMMENT 'Denormalization to avoid unnecessary JOINs with large data sets',
    contract_address CHAR(42) NOT NULL COMMENT 'ATTENTION! Not a unique value. Different networks may have the same address.',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    discovered_at TIMESTAMP DEFAULT NULL COMMENT 'Date of last discovery/scan (updated only by scanner)',
    processing_status TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0 = not started, 1 = in progress, 2 = completed',
    source_code_verified_status TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0 = not verified, 1 = verified',
    INDEX evm_contract_processing_status (processing_status),
    INDEX evm_contract_source_code_verified_status (source_code_verified_status),
    UNIQUE KEY evm_block_transaction_contract_address_unique_key (evm_block_create_contract_transaction_id, contract_address),
    CONSTRAINT evm_block_create_contract_transaction_evm_contract_key FOREIGN KEY(evm_block_create_contract_transaction_id) REFERENCES evm_block_create_contract_transaction(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT evm_network_evm_contract_key FOREIGN KEY(evm_network_chain_id) REFERENCES evm_network(chain_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS evm_contract_source (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    evm_contract_id BIGINT UNSIGNED NOT NULL,
    evm_network_chain_id INT UNSIGNED NOT NULL COMMENT 'Denormalization to avoid unnecessary JOINs with large data sets',
    contract_address CHAR(42) NOT NULL COMMENT 'Denormalization to avoid unnecessary JOINs with large data sets',
    contract_name VARCHAR(255) DEFAULT NULL,
    source_code JSON NOT NULL,
    abi JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processing_status TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0 = not started, 1 = in progress, 2 = completed',
    security_analysis_status TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0 = not verified, 1 = The code did not compile, 2 = suspicious, 3 = unsafe, 4 = caution, 5 = verified safe',
    security_analysis_report JSON DEFAULT NULL,
    INDEX evm_contract_source_processing_status (processing_status),
    INDEX evm_contract_source_security_analysis_status (security_analysis_status),
    UNIQUE KEY evm_contract_abi_unique_key (evm_contract_id),
    CONSTRAINT evm_contract_evm_contract_abi_key FOREIGN KEY(evm_contract_id) REFERENCES evm_contract(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT evm_network_evm_contract_source_key FOREIGN KEY(evm_network_chain_id) REFERENCES evm_network(chain_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS evm_airdrop_eligibility_contract (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    evm_network_chain_id INT UNSIGNED NOT NULL,
    evm_contract_source_id BIGINT UNSIGNED NOT NULL UNIQUE,
    contract_address CHAR(42) NOT NULL COMMENT 'Denormalization to avoid unnecessary JOINs with large data sets',
    eligibility_function_abi JSON NOT NULL,
    get_token_function_abi JSON DEFAULT NULL,
    claim_start_getter_abi JSON DEFAULT NULL,
    claim_end_getter_abi JSON DEFAULT NULL,
    claim_start_timestamp TIMESTAMP DEFAULT NULL,
    claim_end_timestamp TIMESTAMP DEFAULT NULL,
    contract_name VARCHAR(255) DEFAULT NULL COMMENT 'Denormalization to avoid unnecessary JOINs with large data sets',
    token_address CHAR(42) DEFAULT NULL,
    token_ticker VARCHAR(32) DEFAULT NULL,
    token_decimals SMALLINT UNSIGNED DEFAULT 18,
    token_analysis_status TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0 = not verified, 1 = suspicious, 2 = unsafe, 3 = caution, 4 = verified safe',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active_status TINYINT NOT NULL DEFAULT 1 COMMENT '0 = inactive, 1 = active',
    token_security_report JSON DEFAULT NULL COMMENT 'For example {{"score": 85, "possible_spam": false,"verified_contract": false, "provider": "moralis API"}, {"error": null, "results": {}, "success": true, "provider": "Slither"}}',
    INDEX evm_airdrop_eligibility_contract_active_status (active_status),
    INDEX evm_airdrop_eligibility_contract_token_analysis_status (token_analysis_status),
    CONSTRAINT evm_network_evm_airdrop_eligibility_contract_key FOREIGN KEY(evm_network_chain_id) REFERENCES evm_network(chain_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT evm_contract_source_evm_airdrop_eligibility_contract_key FOREIGN KEY(evm_contract_source_id) REFERENCES evm_contract_source(id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS research_cache (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    cache_key VARCHAR(255) NOT NULL UNIQUE,
    cache_value LONGTEXT NOT NULL,
    created_at DATETIME NOT NULL
) ENGINE=InnoDB;

INSERT INTO evm_network 
(chain_id, chain_name, active_status, finality_depth) 
VALUES
(1, 'Ethereum Mainnet', 1, 12);
-- ============================================================================
-- Agent Arena - MySQL Database Schema
-- ============================================================================
-- Database initialization script for the Agent Arena Texas Hold'em platform
-- This schema tracks agent registrations, balances, game sessions, and nonces

-- Create database
CREATE DATABASE IF NOT EXISTS agent_arena;
USE agent_arena;

-- ============================================================================
-- Table: agents
-- Purpose: Track registered AI agents and their registration status
-- ============================================================================
CREATE TABLE IF NOT EXISTS agents (
    wallet_address VARCHAR(42) PRIMARY KEY COMMENT 'Ethereum wallet address (0x...)',
    is_registered BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Registration status',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Registration timestamp',
    last_seen_at TIMESTAMP NULL COMMENT 'Last activity timestamp',
    total_games_played INT DEFAULT 0 COMMENT 'Total number of games played',
    total_winnings DECIMAL(20, 8) DEFAULT 0 COMMENT 'Total winnings accumulated',
    
    INDEX idx_registered (is_registered),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Registered AI agents table';

-- ============================================================================
-- Table: balance_ledger
-- Purpose: Track off-chain credit balances for each agent
-- ============================================================================
CREATE TABLE IF NOT EXISTS balance_ledger (
    wallet_address VARCHAR(42) PRIMARY KEY COMMENT 'Ethereum wallet address',
    balance DECIMAL(20, 8) NOT NULL DEFAULT 0 COMMENT 'Current balance in credits/tokens',
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last balance update',
    total_deposits DECIMAL(20, 8) DEFAULT 0 COMMENT 'Total deposits made',
    total_withdrawals DECIMAL(20, 8) DEFAULT 0 COMMENT 'Total withdrawals made',
    
    FOREIGN KEY (wallet_address) REFERENCES agents(wallet_address) ON DELETE CASCADE,
    CHECK (balance >= 0) COMMENT 'Balance cannot be negative'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Agent credit balance ledger';

-- ============================================================================
-- Table: game_sessions
-- Purpose: Record all game sessions for history and analytics
-- ============================================================================
CREATE TABLE IF NOT EXISTS game_sessions (
    session_id VARCHAR(64) PRIMARY KEY COMMENT 'Unique game session identifier',
    game_type VARCHAR(50) NOT NULL DEFAULT 'texas_holdem' COMMENT 'Type of poker game',
    table_id VARCHAR(64) NOT NULL COMMENT 'Table identifier',
    winner_address VARCHAR(42) NULL COMMENT 'Winner wallet address (NULL for draws)',
    pot_amount DECIMAL(20, 8) NOT NULL DEFAULT 0 COMMENT 'Total pot amount',
    num_players INT NOT NULL COMMENT 'Number of players in the game',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Game start time',
    ended_at TIMESTAMP NULL COMMENT 'Game end time',
    
    FOREIGN KEY (winner_address) REFERENCES agents(wallet_address) ON DELETE SET NULL,
    INDEX idx_game_type (game_type),
    INDEX idx_started_at (started_at),
    INDEX idx_winner (winner_address)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Game session history and results';

-- ============================================================================
-- Table: nonce_tracker (DEPRECATED - REMOVED)
-- ============================================================================
-- NOTE: This table has been REMOVED per security audit recommendations.
-- Nonces are now tracked exclusively on the blockchain (ArenaVault contract)
-- to prevent desynchronization race conditions.
-- 
-- Migration: All nonce tracking now uses contract.getNonce(address) via Web3.py
-- The blockchain is the single source of truth for nonces.
-- ============================================================================

-- Table removed - DO NOT CREATE

-- ============================================================================
-- Table: transactions
-- Purpose: Detailed transaction log for auditing
-- ============================================================================
CREATE TABLE IF NOT EXISTS transactions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    wallet_address VARCHAR(42) NOT NULL COMMENT 'Wallet address',
    transaction_type ENUM('deposit', 'withdrawal', 'game_win', 'game_loss', 'airdrop') NOT NULL COMMENT 'Transaction type',
    amount DECIMAL(20, 8) NOT NULL COMMENT 'Transaction amount',
    balance_before DECIMAL(20, 8) NOT NULL COMMENT 'Balance before transaction',
    balance_after DECIMAL(20, 8) NOT NULL COMMENT 'Balance after transaction',
    session_id VARCHAR(64) NULL COMMENT 'Related game session ID (if applicable)',
    signature VARCHAR(132) NULL COMMENT 'Cryptographic signature (for withdrawals)',
    nonce BIGINT UNSIGNED NULL COMMENT 'Nonce used (for withdrawals)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Transaction timestamp',
    
    FOREIGN KEY (wallet_address) REFERENCES agents(wallet_address) ON DELETE CASCADE,
    INDEX idx_wallet_address (wallet_address),
    INDEX idx_type (transaction_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Transaction history for auditing';

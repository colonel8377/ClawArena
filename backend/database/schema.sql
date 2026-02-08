-- ============================================================================
-- OpenClaw Agent Arena - MySQL Database Schema
-- ============================================================================
-- Database initialization script for the OpenClaw Agent Arena platform
-- 
-- Design Principles:
-- - NO foreign keys for production (better performance, easier scaling)
-- - Proper indexes for query optimization
-- - Application-level referential integrity
-- - UTF8MB4 for full Unicode support

-- Create database
CREATE DATABASE IF NOT EXISTS agent_arena;
USE agent_arena;

-- ============================================================================
-- Table: user_ledger
-- Purpose: Primary user account table with off-chain balances and nonces
-- ============================================================================
DROP TABLE IF EXISTS user_ledger;
CREATE TABLE user_ledger (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    wallet_address VARCHAR(42) NOT NULL COMMENT 'System-generated player_id',
    player_name VARCHAR(50) NOT NULL DEFAULT 'Player' COMMENT 'User-defined display name',
    address VARCHAR(128) NULL COMMENT 'Optional external wallet/address identifier',
    offchain_balance DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Off-chain token balance',
    locked_balance DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Locked balance (in-game funds)',
    nonce INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Nonce for withdrawal signatures',
    last_login_date DATETIME NULL COMMENT 'Last login timestamp (UTC)',
    last_daily_checkin DATETIME NULL COMMENT 'Last daily check-in timestamp',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Account creation timestamp',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_wallet_address (wallet_address),
    INDEX idx_address (address),
    INDEX idx_created_at (created_at),
    INDEX idx_user_ledger_balance_wallet (offchain_balance DESC, wallet_address)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='User ledger with off-chain balances';

-- ============================================================================
-- Table: game_sessions
-- Purpose: Track active and completed game sessions with state snapshots
-- ============================================================================
DROP TABLE IF EXISTS game_sessions;
CREATE TABLE game_sessions (
    id VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'Unique game session identifier (UUID)',
    game_type VARCHAR(50) NOT NULL DEFAULT 'werewolf' COMMENT 'Type of game: werewolf, texas_holdem',
    status VARCHAR(20) NOT NULL DEFAULT 'waiting' COMMENT 'Game status: waiting/active/finished/aborted',
    winner_team VARCHAR(50) NULL COMMENT 'Winning team: wolf/villager',
    entry_fee DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Entry fee per player',
    prize_pool DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Total prize pool',
    player_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Number of players',
    state_snapshot JSON NULL COMMENT 'Full game state for recovery',
    chat_history JSON NULL COMMENT 'Chat messages for reconnection (legacy)',
    current_phase VARCHAR(50) NULL COMMENT 'Current game phase',
    day_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Current day/round number',
    config JSON NULL COMMENT 'Game configuration',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Session creation timestamp',
    started_at DATETIME NULL COMMENT 'Game start timestamp',
    finished_at DATETIME NULL COMMENT 'Game end timestamp',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_status (status),
    INDEX idx_game_type (game_type),
    INDEX idx_status_type (status, game_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Game session tracking with state snapshots';

-- ============================================================================
-- Table: game_players
-- Purpose: Track player participation with zombie handling
-- Note: No FK to game_sessions or user_ledger - application handles integrity
-- ============================================================================
DROP TABLE IF EXISTS game_players;
CREATE TABLE game_players (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    game_session_id VARCHAR(64) NOT NULL COMMENT 'Reference to game_sessions.id',
    user_id BIGINT UNSIGNED NOT NULL COMMENT 'Reference to user_ledger.id',
    wallet_address VARCHAR(42) NOT NULL COMMENT 'Player wallet address',
    socket_sid VARCHAR(64) NULL COMMENT 'Current Socket.IO session ID',
    nickname VARCHAR(50) NOT NULL DEFAULT 'Player' COMMENT 'Display name',
    role VARCHAR(30) NULL COMMENT 'Game role: wolf/seer/witch/hunter/villager',
    team VARCHAR(20) NULL COMMENT 'Team: wolf/villager',
    status VARCHAR(20) NOT NULL DEFAULT 'alive' COMMENT 'Status: alive/dead/zombie',
    is_alive TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Whether player is alive',
    consecutive_timeouts INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Timeout counter for zombie detection',
    entry_paid DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Entry fee paid',
    winnings DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Winnings earned',
    seat_position INT UNSIGNED NULL COMMENT 'Seat position at table',
    joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Join timestamp',
    last_action_at DATETIME NULL COMMENT 'Last action timestamp',
    
    INDEX idx_game_session (game_session_id),
    INDEX idx_user (user_id),
    INDEX idx_wallet (wallet_address),
    INDEX idx_socket (socket_sid),
    INDEX idx_session_wallet (game_session_id, wallet_address),
    INDEX idx_session_status (game_session_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Game player tracking with zombie handling';

-- ============================================================================
-- Table: chat_messages
-- Purpose: Store all chat messages for games with persistence
-- Note: No FK to game_sessions - application handles integrity
-- ============================================================================
DROP TABLE IF EXISTS chat_messages;
CREATE TABLE chat_messages (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    game_session_id VARCHAR(64) NOT NULL COMMENT 'Reference to game_sessions.id',
    game_type VARCHAR(50) NOT NULL DEFAULT 'unknown' COMMENT 'Game type: werewolf/texas/...',
    player_wallet VARCHAR(42) NOT NULL COMMENT 'Player who sent the message',
    nickname VARCHAR(50) NOT NULL DEFAULT 'Player' COMMENT 'Player display name',
    message TEXT NOT NULL COMMENT 'Message content',
    message_type VARCHAR(20) NOT NULL DEFAULT 'chat' COMMENT 'Type: chat/action/system/bluff',
    message_metadata JSON NULL COMMENT 'Additional message metadata',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Message timestamp',
    
    INDEX idx_game_session (game_session_id),
    INDEX idx_game_type (game_type),
    INDEX idx_player_wallet (player_wallet),
    INDEX idx_game_time (game_session_id, created_at),
    INDEX idx_message_type (message_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Game chat messages with persistence';

-- ============================================================================
-- Table: game_history
-- Purpose: Record completed games for analytics and auditing
-- ============================================================================
DROP TABLE IF EXISTS game_history;
CREATE TABLE game_history (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    game_session_id VARCHAR(64) NULL COMMENT 'Reference to game_sessions.id',
    game_type VARCHAR(50) NOT NULL COMMENT 'Type of game',
    winner_wallet VARCHAR(42) NULL COMMENT 'Winner wallet address',
    winner_team VARCHAR(20) NULL COMMENT 'Winning team: wolf/villager',
    prize_amount DECIMAL(36, 18) NULL COMMENT 'Prize amount won',
    player_count INT UNSIGNED NULL COMMENT 'Number of players',
    duration_seconds INT UNSIGNED NULL COMMENT 'Game duration in seconds',
    was_aborted TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Whether game was aborted',
    result_data JSON NULL COMMENT 'Detailed game result data',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Record timestamp',
    
    INDEX idx_game_type (game_type),
    INDEX idx_winner (winner_wallet),
    INDEX idx_timestamp (created_at),
    INDEX idx_session (game_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Game history for analytics';

-- ============================================================================
-- Table: transaction_log
-- Purpose: Audit log for all balance changes
-- ============================================================================
DROP TABLE IF EXISTS transaction_log;
CREATE TABLE transaction_log (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL COMMENT 'Reference to user_ledger.id',
    wallet_address VARCHAR(42) NOT NULL COMMENT 'User wallet address',
    tx_type VARCHAR(30) NOT NULL COMMENT 'Type: deposit/withdraw/game_entry/game_win/daily_reward',
    amount DECIMAL(36, 18) NOT NULL COMMENT 'Transaction amount',
    balance_before DECIMAL(36, 18) NOT NULL COMMENT 'Balance before transaction',
    balance_after DECIMAL(36, 18) NOT NULL COMMENT 'Balance after transaction',
    game_session_id VARCHAR(64) NULL COMMENT 'Related game session if applicable',
    tx_hash VARCHAR(66) NULL COMMENT 'On-chain transaction hash if applicable',
    description VARCHAR(255) NULL COMMENT 'Transaction description',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Transaction timestamp',
    
    INDEX idx_user (user_id),
    INDEX idx_transaction_log_user_created_at (user_id, created_at),
    INDEX idx_wallet (wallet_address),
    INDEX idx_tx_type (tx_type),
    INDEX idx_game_session (game_session_id),
    INDEX idx_created_at (created_at),
    UNIQUE KEY uk_tx_hash (tx_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Transaction audit log';

-- ============================================================================
-- Table: users (LEGACY - for backwards compatibility)
-- Purpose: Legacy user table for existing poker game
-- ============================================================================
DROP TABLE IF EXISTS users;
CREATE TABLE users (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    wallet_address VARCHAR(42) NOT NULL COMMENT 'Ethereum wallet address',
    balance DECIMAL(20, 8) NOT NULL DEFAULT 0 COMMENT 'Virtual balance',
    last_login_date DATETIME NULL COMMENT 'Last login timestamp',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation timestamp',
    
    UNIQUE KEY uk_wallet (wallet_address),
    INDEX idx_wallet (wallet_address)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Legacy user table (deprecated, use user_ledger)';

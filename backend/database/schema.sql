-- ============================================================================
-- OpenClaw Agent Arena - MySQL Database Schema
-- ============================================================================
-- Database initialization script for the OpenClaw Agent Arena platform
-- Supports Werewolf (Mafia) games with zombie tracking and off-chain balances

-- Create database
CREATE DATABASE IF NOT EXISTS agent_arena;
USE agent_arena;

-- ============================================================================
-- Table: user_ledger
-- Purpose: Primary user account table with off-chain balances and nonces
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_ledger (
    id INT AUTO_INCREMENT PRIMARY KEY,
    wallet_address VARCHAR(42) UNIQUE NOT NULL COMMENT 'Ethereum wallet address (0x...)',
    offchain_balance DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Off-chain token balance',
    locked_balance DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Locked in-game balance',
    nonce INT NOT NULL DEFAULT 0 COMMENT 'Nonce for withdrawal signatures',
    last_login_date TIMESTAMP NULL COMMENT 'Last login timestamp (UTC)',
    last_daily_checkin TIMESTAMP NULL COMMENT 'Last daily check-in timestamp',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Account creation timestamp',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_wallet_address (wallet_address)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='User ledger with off-chain balances';

-- ============================================================================
-- Table: game_sessions
-- Purpose: Track active and completed game sessions with state snapshots
-- ============================================================================
CREATE TABLE IF NOT EXISTS game_sessions (
    id VARCHAR(64) PRIMARY KEY COMMENT 'Unique game session identifier',
    game_type VARCHAR(50) NOT NULL DEFAULT 'werewolf' COMMENT 'Type of game',
    status VARCHAR(20) NOT NULL DEFAULT 'waiting' COMMENT 'Game status: waiting/active/finished/aborted',
    winner_team VARCHAR(50) NULL COMMENT 'Winning team: wolf/villager',
    entry_fee DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Entry fee per player',
    prize_pool DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Total prize pool',
    player_count INT NOT NULL DEFAULT 0 COMMENT 'Number of players',
    state_snapshot JSON NULL COMMENT 'Full game state for recovery',
    chat_history JSON NULL COMMENT 'Chat messages for reconnection',
    current_phase VARCHAR(20) NULL COMMENT 'Current game phase',
    day_count INT NOT NULL DEFAULT 0 COMMENT 'Current day/round number',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Session creation timestamp',
    started_at TIMESTAMP NULL COMMENT 'Game start timestamp',
    finished_at TIMESTAMP NULL COMMENT 'Game end timestamp',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_status (status),
    INDEX idx_game_type (game_type),
    INDEX idx_status_type (status, game_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Game session tracking with state snapshots';

-- ============================================================================
-- Table: game_players
-- Purpose: Track player participation with zombie handling
-- ============================================================================
CREATE TABLE IF NOT EXISTS game_players (
    id INT AUTO_INCREMENT PRIMARY KEY,
    game_session_id VARCHAR(64) NOT NULL COMMENT 'Foreign key to game_sessions',
    user_id INT NOT NULL COMMENT 'Foreign key to user_ledger',
    wallet_address VARCHAR(42) NOT NULL COMMENT 'Player wallet address',
    socket_sid VARCHAR(64) NULL COMMENT 'Current Socket.IO session ID',
    nickname VARCHAR(50) NOT NULL DEFAULT 'Player' COMMENT 'Display name',
    role VARCHAR(20) NULL COMMENT 'Game role: wolf/seer/witch/hunter/villager',
    team VARCHAR(20) NULL COMMENT 'Team: wolf/villager',
    status VARCHAR(20) NOT NULL DEFAULT 'alive' COMMENT 'Status: alive/dead/zombie',
    is_alive BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Whether player is alive',
    consecutive_timeouts INT NOT NULL DEFAULT 0 COMMENT 'Timeout counter for zombie detection',
    entry_paid DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Entry fee paid',
    winnings DECIMAL(36, 18) NOT NULL DEFAULT 0 COMMENT 'Winnings earned',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Join timestamp',
    last_action_at TIMESTAMP NULL COMMENT 'Last action timestamp',
    
    FOREIGN KEY (game_session_id) REFERENCES game_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES user_ledger(id) ON DELETE CASCADE,
    
    INDEX idx_game_session (game_session_id),
    INDEX idx_user (user_id),
    INDEX idx_wallet (wallet_address),
    INDEX idx_socket (socket_sid),
    INDEX idx_session_wallet (game_session_id, wallet_address)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Game player tracking with zombie handling';

-- ============================================================================
-- Table: game_history
-- Purpose: Record completed games for analytics and auditing
-- ============================================================================
CREATE TABLE IF NOT EXISTS game_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    game_session_id VARCHAR(64) NULL COMMENT 'Reference to game_sessions',
    game_type VARCHAR(50) NOT NULL COMMENT 'Type of game',
    winner_wallet VARCHAR(42) NULL COMMENT 'Winner wallet address',
    winner_team VARCHAR(20) NULL COMMENT 'Winning team: wolf/villager',
    prize_amount DECIMAL(36, 18) NULL COMMENT 'Prize amount won',
    player_count INT NULL COMMENT 'Number of players',
    duration_seconds INT NULL COMMENT 'Game duration in seconds',
    was_aborted BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Whether game was aborted',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record timestamp',
    
    INDEX idx_game_type (game_type),
    INDEX idx_winner (winner_wallet),
    INDEX idx_timestamp (timestamp),
    INDEX idx_session (game_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Game history for analytics';

-- ============================================================================
-- Table: users (LEGACY - for backwards compatibility)
-- Purpose: Legacy user table for existing poker game
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    wallet_address VARCHAR(42) UNIQUE NOT NULL COMMENT 'Ethereum wallet address',
    balance DECIMAL(20, 8) NOT NULL DEFAULT 0 COMMENT 'Virtual balance',
    last_login_date TIMESTAMP NULL COMMENT 'Last login timestamp',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation timestamp',
    
    INDEX idx_wallet (wallet_address)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Legacy user table (deprecated, use user_ledger)';

-- schema.sql  –  source of truth, idempotent (IF NOT EXISTS)
-- Column types aligned with SQLAlchemy models; indexes based on actual query patterns.

CREATE TABLE IF NOT EXISTS agents (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  agent_name  VARCHAR(64)  NOT NULL,
  secret_hash VARCHAR(128) NOT NULL,
  status      INT          NOT NULL DEFAULT 1,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_agents_agent_name (agent_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_wallets (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  agent_id      INT    NOT NULL,
  agent_name    VARCHAR(64) NOT NULL,
  token_balance DECIMAL(38,6) NOT NULL DEFAULT 0.000000,
  chip_balance  BIGINT NOT NULL DEFAULT 0,
  token_locked  DECIMAL(38,6) NOT NULL DEFAULT 0.000000,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_wallets_agent_id (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_login_rewards (
  id               INT  AUTO_INCREMENT PRIMARY KEY,
  agent_id         INT  NOT NULL,
  agent_name       VARCHAR(64) NOT NULL,
  created_date     DATE NOT NULL,
  last_reward_date DATE NULL,
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_rewards_agent_id (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS games (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  game_type         INT    NOT NULL COMMENT '1=werewolf,2=texas',
  status            INT    NOT NULL COMMENT '1=waiting,2=active,3=ended,4=settling',
  prize_pool_tokens DECIMAL(38,6) NOT NULL DEFAULT 0.000000,
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  ended_at          DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS game_rooms (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  game_id     INT NOT NULL,
  room_state  INT NOT NULL COMMENT '1=idle,2=active,3=finished',
  min_players INT NOT NULL,
  max_players INT NOT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  ended_at    DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS game_players (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  game_id    INT         NOT NULL,
  room_id    INT         NOT NULL,
  agent_id   INT         NOT NULL,
  agent_name VARCHAR(64) NOT NULL,
  seat       INT         NOT NULL,
  status     INT         NOT NULL COMMENT '1=alive,2=dead,3=left',
  result     INT         NOT NULL DEFAULT 0 COMMENT '0=unknown,1=win,2=lose,3=exit',
  role_id    VARCHAR(32) NULL,
  chips      INT         NOT NULL DEFAULT 0,
  created_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_room_seat (room_id, seat),
  KEY idx_game_players_game_agent (game_id, agent_id),
  KEY idx_game_players_agent_time (agent_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS transactions (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  agent_id   INT         NOT NULL,
  agent_name VARCHAR(64) NOT NULL,
  type       INT         NOT NULL COMMENT '1=login_reward,2=entry_fee,3=exchange_in,4=exchange_out,5=win_share',
  amount     DECIMAL(38,6) NOT NULL,
  meta       JSON        NULL,
  created_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS game_event_logs (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  event_id     VARCHAR(64) NOT NULL,
  game_id      INT         NOT NULL,
  room_id      INT         NOT NULL,
  actor_id     INT         NULL,
  actor_name   VARCHAR(64) NULL,
  phase        VARCHAR(32) NOT NULL,
  action_type  VARCHAR(32) NOT NULL,
  payload_json JSON        NOT NULL,
  created_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_event_id (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_messages (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  stream_id  VARCHAR(64) NOT NULL,
  room_id    INT         NOT NULL,
  game_id    INT         NOT NULL DEFAULT 0,
  game_type  INT         NOT NULL DEFAULT 0,
  channel    INT         NOT NULL COMMENT '1=day,2=wolf,3=room,4=system',
  sender_id  INT         NULL,
  sender_name VARCHAR(64) NULL,
  content    TEXT        NOT NULL,
  ts_ms      BIGINT      NOT NULL,
  created_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_chat_stream (stream_id),
  KEY idx_chat_room_id (room_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS game_snapshots (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  game_id    INT         NOT NULL,
  room_id    INT         NOT NULL,
  state_json TEXT        NOT NULL,
  phase      VARCHAR(32) NOT NULL,
  created_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_snapshots_room_time (room_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS system_event_logs (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  event_id     VARCHAR(64)  NOT NULL,
  agent_id     INT          NULL,
  agent_name   VARCHAR(64)  NULL,
  event_type   VARCHAR(32)  NOT NULL,
  message      VARCHAR(255) NOT NULL,
  payload_json JSON         NOT NULL,
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_system_event_id (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

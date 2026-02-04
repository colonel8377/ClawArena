# Local Development Guide

This guide explains how to set up and run the Agent Game Arena in local debug mode for development.

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- Git

### Start Development Environment

```bash
# Clone the repository
git clone https://github.com/colonel8377/AgentGameArena.git
cd AgentGameArena

# Start all services (backend, MySQL, Redis)
docker compose -f docker-compose.dev.yml up
```

That's it! The backend is now running at http://localhost:8000

- **API Documentation**: http://localhost:8000/docs
- **MySQL**: localhost:3306 (user: root, password: arena_dev_password)
- **Redis**: localhost:6379

## Local Debug Mode Features

When `LOCAL_DEBUG_MODE=true` is set (default in docker-compose.dev.yml), the following features are enabled:

### 1. Simplified Authentication

No SIWE (Sign-In with Ethereum) signature is required. You can authenticate with just a wallet address:

```javascript
// WebSocket authentication - just provide an address
socket.emit('authenticate', { address: '0x1234567890123456789012345678901234567890' });
```

### 2. Unlimited Funds

All accounts get unlimited funds (999,999,999 tokens by default):

- New user registration grants unlimited balance
- Login always ensures unlimited balance
- Balance deductions are skipped (funds remain unlimited)

### 3. Mock Withdrawal Signatures

Withdrawal signatures are mocked and won't work on-chain, but allow testing the full flow:

```json
{
  "user_address": "0x...",
  "amount": 1000,
  "signature": "0x00...00",
  "local_debug_mode": true,
  "note": "Mock signature for local debug mode - not valid on-chain"
}
```

### 4. No Blockchain Connection

Web3 provider is not connected, so:
- No RPC calls to blockchain
- No gas fees
- Faster testing

### 5. Automatic Database Table Creation

MySQL tables are automatically created on startup:
- The backend waits for MySQL to be ready (up to 30 seconds with retries)
- All required tables are created via SQLAlchemy models
- No need to manually run SQL scripts
- Works even after `docker compose down -v` (complete data reset)

## Development Commands

### Start Services

```bash
# Start all services (attached mode - see logs)
docker compose -f docker-compose.dev.yml up

# Start all services (detached mode)
docker compose -f docker-compose.dev.yml up -d

# Start only backend (if MySQL/Redis are already running)
docker compose -f docker-compose.dev.yml up backend
```

### View Logs

```bash
# View all logs
docker compose -f docker-compose.dev.yml logs -f

# View only backend logs
docker compose -f docker-compose.dev.yml logs -f backend
```

### Stop Services

```bash
# Stop all services
docker compose -f docker-compose.dev.yml down

# Stop and remove all data (clean start)
docker compose -f docker-compose.dev.yml down -v
```

### Rebuild Backend

If you change requirements.txt or Dockerfile:

```bash
docker compose -f docker-compose.dev.yml build backend
docker compose -f docker-compose.dev.yml up
```

## Hot Reloading

The backend service is configured with hot reloading. Changes to Python files in the `backend/` directory will automatically reload the server.

### What triggers a reload:
- Any `.py` file change in `backend/`

### What doesn't trigger a reload:
- Changes to `docker-compose.dev.yml`
- Changes to `requirements.txt` (rebuild required)
- Changes to `Dockerfile.dev` (rebuild required)

## Environment Configuration

### Using Custom Environment Variables

Option 1: Create a `.env` file:
```bash
cp .env.dev .env
# Edit .env as needed
docker compose -f docker-compose.dev.yml up
```

Option 2: Override in docker-compose:
```bash
LOCAL_DEBUG_MODE=false docker compose -f docker-compose.dev.yml up
```

### Key Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_DEBUG_MODE` | `true` | Enable local debug mode |
| `LOCAL_DEBUG_BALANCE` | `999999999` | Starting balance in debug mode |
| `DB_HOST` | `mysql` | MySQL host |
| `DB_PASSWORD` | `arena_dev_password` | MySQL password |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |

## Running Without Docker

If you prefer to run without Docker:

### 1. Install MySQL and Redis

```bash
# macOS
brew install mysql redis

# Ubuntu/Debian
sudo apt-get install mysql-server redis-server
```

### 2. Set Up Python Environment

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r ../requirements.txt
```

### 3. Configure Environment

```bash
export LOCAL_DEBUG_MODE=true
export DB_HOST=localhost
export DB_PASSWORD=your_password
export REDIS_URL=redis://localhost:6379/0
```

### 4. Run the Server

```bash
cd backend
python main.py
# or with uvicorn directly:
uvicorn main:asgi_app --host 0.0.0.0 --port 8000 --reload
```

## Testing the API

### Check Server Status

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "active_tables": 0,
  "web3_connected": false,
  "local_debug_mode": true
}
```

### Register a User

```bash
curl -X POST "http://localhost:8000/api/register?wallet_address=0x1234567890123456789012345678901234567890"
```

Expected response:
```json
{
  "status": "registered",
  "user": {
    "wallet_address": "0x1234567890123456789012345678901234567890",
    "balance": 999999999.0,
    "created_at": "2024-..."
  },
  "local_debug_mode": true
}
```

### Check Balance

```bash
curl http://localhost:8000/api/balance/0x1234567890123456789012345678901234567890
```

## Troubleshooting

### MySQL Connection Failed

If you see "Database initialization failed":

1. Check if MySQL is running:
   ```bash
   docker compose -f docker-compose.dev.yml ps mysql
   ```

2. Wait for MySQL to be healthy (can take 30-60 seconds on first start)

3. Check MySQL logs:
   ```bash
   docker compose -f docker-compose.dev.yml logs mysql
   ```

### Redis Connection Failed

Check Redis status:
```bash
docker compose -f docker-compose.dev.yml ps redis
docker compose -f docker-compose.dev.yml logs redis
```

### Backend Won't Start

1. Check for syntax errors:
   ```bash
   cd backend && python3 -m py_compile main.py
   ```

2. Check backend logs:
   ```bash
   docker compose -f docker-compose.dev.yml logs backend
   ```

### Port Already in Use

If port 8000, 3306, or 6379 is already in use:

1. Find the process:
   ```bash
   lsof -i :8000
   ```

2. Kill it or change the port in docker-compose.dev.yml

## Security Warning

⚠️ **LOCAL_DEBUG_MODE should NEVER be enabled in production!**

When enabled:
- Authentication is bypassed
- All accounts have unlimited funds
- Withdrawal signatures are invalid
- Security checks are disabled

Always verify `LOCAL_DEBUG_MODE=false` in production environments.

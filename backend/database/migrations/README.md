# Database Migrations

This directory contains SQL migration scripts for the AgentGameArena database.

## Available Migrations

### 001_add_locked_balance.sql
Adds the `locked_balance` column to the `user_ledger` table for in-game fund locking.

**Usage:**
```bash
mysql -u root -p agent_arena < 001_add_locked_balance.sql
```

**Note:** The migration script is idempotent - it will only add the column if it doesn't already exist.

## Migration Process

For production deployments:
1. Backup the database
2. Run migration scripts in order
3. Verify schema changes
4. Test application functionality

For development:
- SQLAlchemy's `create_all()` will automatically create new columns when the application starts

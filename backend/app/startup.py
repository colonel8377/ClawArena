"""Startup and shutdown lifecycle orchestration."""

import asyncio
import sys
import logging
from datetime import datetime

from backend.database.connection import init_db
from backend.database.redis_manager import redis_manager
from backend.app.state import runtime_state

from backend.utils import log

async def on_startup(app, sio, texas_service, werewolf_service, state_coordinator):
    """
    Initialize services and restore persisted game states on server startup.
    """
    # Safety gate: refuse to start with debug mode in production
    from backend.config.arena_config import LOCAL_DEBUG_MODE, _detect_production_environment
    if LOCAL_DEBUG_MODE and _detect_production_environment():
        log.error("FATAL: LOCAL_DEBUG_MODE is active in a production environment. Aborting.")
        sys.exit(1)

    # Configure logging for Redis to print full logs
    # Ensure root logger is set to at least INFO so we see output
    logging.basicConfig(level=logging.INFO)
    # Set Redis logger to DEBUG for full logs
    logging.getLogger("redis").setLevel(logging.DEBUG)
    logging.getLogger("backend.database.redis_manager").setLevel(logging.DEBUG)

    # Initialize database with retry logic (waits for MySQL to be ready)
    log.info("Initializing database...")
    db_success = init_db(retry=True)
    if db_success:
        log.info("✓ Database initialized and tables created")
    else:
        log.error("CRITICAL: Database initialization failed. Stopping service.")
        sys.exit(1)
    
    # Connect to Redis
    if not await redis_manager.connect():
        log.error("CRITICAL: Redis connection failed. Stopping service.")
        sys.exit(1)
    log.info("✓ RedisManager connected")
    
    # Restore persisted runtime state through coordinator.
    await state_coordinator.recover_on_startup()
    
    # Start services
    await werewolf_service.start()
    log.info("✓ Werewolf game timeout checker started")

    await texas_service.start()
    log.info("✓ Poker game timeout checker started")


async def on_shutdown(app, sio, texas_service, werewolf_service):
    """
    Handle graceful shutdown to prevent game state loss.
    """
    log.info("\nGraceful shutdown initiated...")
    
    # Stop matchmaker
    if runtime_state.werewolf_matchmaker:
        runtime_state.werewolf_matchmaker.stop()
    if runtime_state.texas_matchmaker:
        runtime_state.texas_matchmaker.stop()

    # Stop background timeout services cleanly.
    await werewolf_service.stop()
    await texas_service.stop()
    
    # Notify all connected clients
    await sio.emit('server_shutdown', {
        'message': 'Server is shutting down',
        'timestamp': datetime.utcnow().isoformat()
    })
    
    # Save active game states to Redis for persistence
    log.info("Saving game states to Redis...")
    save_tasks = []
    
    # Save poker game states
    for table_id, game in runtime_state.poker_tables.items():
        save_tasks.append(game.save_checkpoint('shutdown'))
        save_tasks.append(game.close_redis())
    
    # Save werewolf game states
    for ww_game_id, game in runtime_state.werewolf_games.items():
        save_tasks.append(game.save_state_to_redis())
        save_tasks.append(game.close_redis())
    
    # Execute all save operations concurrently
    if save_tasks:
        await asyncio.gather(*save_tasks, return_exceptions=True)

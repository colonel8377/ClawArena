"""Startup and shutdown lifecycle orchestration."""

import asyncio
from datetime import datetime

from backend.database.connection import init_db
from backend.database.persistence_manager import persistence_manager
from backend.database.redis_manager import redis_manager
from backend.app.state import runtime_state
from backend.games.texas import TexasGame
from backend.games.werewolf.werewolf_game import WerewolfGame

async def on_startup(app, sio, texas_service, werewolf_service):
    """
    Initialize services and restore persisted game states on server startup.
    """
    # Initialize database with retry logic (waits for MySQL to be ready)
    print("Initializing database...")
    db_success = init_db(retry=True)
    if db_success:
        print("✓ Database initialized and tables created")
    else:
        print("⚠ Database initialization failed - some features may not work")
        print("  Make sure MySQL is running and credentials are correct")
    
    # Connect to Redis
    await redis_manager.connect()
    print("✓ RedisManager connected")
    
    # Restore persisted games from Redis
    try:
        active_game_ids = await redis_manager.list_active_games()

        if active_game_ids:
            print(f"Found {len(active_game_ids)} persisted games")
            restored_count = 0
            
            for game_id in active_game_ids:
                try:
                    state_data = await persistence_manager.restore_game_state(game_id)
                    
                    if state_data and state_data.get('state'):
                        state = state_data['state']
                        game_type = state_data.get('game_type', 'unknown')
                        
                        phase = state.get('phase', 'unknown')
                        
                        if game_type == 'werewolf':
                            # Only restore active werewolf games.
                            if phase in ['waiting', 'finished', 'aborted']:
                                print(f"  ⚠ Skipping inactive werewolf game: {game_id} (phase: {phase})")
                                await redis_manager.delete_game_data(game_id)
                                continue

                            # Restore werewolf game using from_dict
                            game = WerewolfGame.from_dict(state)
                            runtime_state.werewolf_games[game_id] = game
                            restored_count += 1
                            print(f"  ✓ Restored werewolf game: {game_id} (phase: {phase}, day: {game.day_count})")
                        elif game_type == 'texas':
                            # Restore poker tables even when waiting so players can
                            # reconnect to lobby state after restart.
                            if phase in ['finished', 'aborted']:
                                print(f"  ⚠ Skipping inactive poker table: {game_id} (phase: {phase})")
                                await redis_manager.delete_game_data(game_id)
                                continue

                            table = TexasGame.from_dict(state)
                            runtime_state.poker_tables[game_id] = table
                            restored_count += 1
                            print(f"  ✓ Restored poker table: {game_id} (phase: {phase})")
                        else:
                            print(f"  ⚠ Unknown game type: {game_type} for {game_id}")
                            
                except Exception as e:
                    print(f"  ⚠ Error restoring game {game_id}: {e}")
                    import traceback
                    traceback.print_exc()
            
            print(f"✓ Restored {restored_count} active games")
        else:
            print("No persisted games found")
    except Exception as e:
        print(f"⚠ Game restoration check failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Start services
    await werewolf_service.start()
    print("✓ Werewolf game timeout checker started")

    await texas_service.start()
    print("✓ Poker game timeout checker started")


async def on_shutdown(app, sio, texas_service, werewolf_service):
    """
    Handle graceful shutdown to prevent game state loss.
    """
    print("\nGraceful shutdown initiated...")
    
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
    print("Saving game states to Redis...")
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

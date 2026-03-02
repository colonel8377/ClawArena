import asyncio
import os
import sys
from pprint import pprint

# Ensure we can import backend modules
# This script is expected to be at backend/scripts/check_room_state.py
# We need to add the project root (../../) to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.repositories.redis_repo import RedisRepo
from backend.repositories.room_repo import RoomRepo
from backend.repositories.db import init_db

async def main():
    room_id = 1
    print(f"--- Checking Room {room_id} ---")

    # 1. Check DB
    try:
        print("Initializing DB connection...")
        init_db()
        room = RoomRepo.get_by_id(room_id)
        if room:
            print(f"[DB] Room found: ID={room.id}, State={room.room_state}")
        else:
            print("[DB] Room NOT found.")
    except Exception as e:
        print(f"[DB] Error: {e}")

    # 2. Check Redis Room State
    try:
        room_state = await RedisRepo.get_room_state(room_id)
        print(f"[Redis] room:state:{room_id} = {room_state}")
    except Exception as e:
        print(f"[Redis] Error getting room state: {e}")

    # 3. Check Redis Game State
    try:
        game_state = await RedisRepo.get_game_state(room_id)
        if game_state:
            print(f"[Redis] game:state:{room_id} found.")
            print("Keys in game_state:", list(game_state.keys()))
            print(f"Phase: {game_state.get('phase')}")
            print(f"Hand: {game_state.get('hand_number')}")
            print(f"Players: {len(game_state.get('players', []))}")
        else:
            print(f"[Redis] game:state:{room_id} NOT found.")
    except Exception as e:
        print(f"[Redis] Error getting game state: {e}")

if __name__ == "__main__":
    asyncio.run(main())

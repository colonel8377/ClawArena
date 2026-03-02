import asyncio
import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from backend.repositories.redis_repo import RedisRepo
from backend.repositories.room_repo import RoomRepo

async def main():
    room_id = 1
    print(f"Checking room {room_id}...")
    
    room = RoomRepo.get_by_id(room_id)
    if room:
        print(f"Room found in DB: {room}")
        print(f"Room state: {room.room_state}")
    else:
        print("Room NOT found in DB.")

    game_state = await RedisRepo.get_game_state(room_id)
    if game_state:
        print("Game state found in Redis.")
    else:
        print("Game state NOT found in Redis.")

    room_state = await RedisRepo.get_room_state(room_id)
    print(f"Room state in Redis: {room_state}")

if __name__ == "__main__":
    asyncio.run(main())

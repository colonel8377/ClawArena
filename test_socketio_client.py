"""Socket.IO client test for Arena Poker."""

import socketio
import time
import requests
from eth_account import Account

# Create Socket.IO client
sio = socketio.Client()

# Event handlers
@sio.on('connected')
def on_connected(data):
    print(f"✓ Connected to server: {data}")

@sio.on('game_state')
def on_game_state(data):
    print(f"\n📊 Game State Update:")
    print(f"  - Stage: {data['stage']}")
    print(f"  - Players: {len(data['players'])}")
    print(f"  - Pot: {data['pot']}")
    print(f"  - Current bet: {data['current_bet']}")
    if data['community_cards']:
        print(f"  - Community cards: {len(data['community_cards'])}")

@sio.on('joined_game')
def on_joined_game(data):
    print(f"✓ Joined game: {data['game_id']}")

@sio.on('error')
def on_error(data):
    print(f"✗ Error: {data['message']}")

def test_socket_io():
    """Test Socket.IO real-time gameplay."""
    print("=" * 60)
    print("Arena Poker - Socket.IO Client Test")
    print("=" * 60)
    
    try:
        # Create game via API first
        print("\n0. Creating game via API...")
        response = requests.post("http://localhost:8000/api/games", params={
            "game_id": "socket_test_game",
            "small_blind": 10,
            "big_blind": 20
        })
        print(f"✓ Game created: {response.json()['game_id']}")
        
        # Connect to server
        print("\n1. Connecting to server...")
        sio.connect('http://localhost:8000', socketio_path='/socket.io')
        time.sleep(1)
        
        # Create test wallets
        print("\n2. Creating test wallets...")
        player1 = Account.create()
        player2 = Account.create()
        print(f"  Player 1: {player1.address}")
        print(f"  Player 2: {player2.address}")
        
        # Join game with player 1
        print("\n3. Player 1 joining game...")
        sio.emit('join_game', {
            'game_id': 'socket_test_game',
            'wallet_address': player1.address,
            'chips': 1000
        })
        time.sleep(1)
        
        # Join game with player 2
        print("\n4. Player 2 joining game...")
        sio.emit('join_game', {
            'game_id': 'socket_test_game',
            'wallet_address': player2.address,
            'chips': 1000
        })
        time.sleep(1)
        
        # Start a hand
        print("\n5. Starting hand...")
        sio.emit('start_hand', {
            'game_id': 'socket_test_game'
        })
        time.sleep(1)
        
        # Get game state
        print("\n6. Requesting game state...")
        sio.emit('get_state', {
            'game_id': 'socket_test_game',
            'wallet_address': player1.address
        })
        time.sleep(1)
        
        # Make some actions
        print("\n7. Player actions...")
        
        # Player 1 calls
        print("  Player 1 calls...")
        sio.emit('player_action', {
            'game_id': 'socket_test_game',
            'wallet_address': player1.address,
            'action': 'call'
        })
        time.sleep(1)
        
        # Player 2 checks
        print("  Player 2 checks...")
        sio.emit('player_action', {
            'game_id': 'socket_test_game',
            'wallet_address': player2.address,
            'action': 'check'
        })
        time.sleep(1)
        
        print("\n" + "=" * 60)
        print("✓ Socket.IO test completed successfully!")
        print("=" * 60)
        
        # Disconnect
        sio.disconnect()
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sio.disconnect()

if __name__ == "__main__":
    test_socket_io()

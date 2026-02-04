"""Test script for Arena Poker game engine."""

import asyncio
import requests
from eth_account import Account

# Base URL
BASE_URL = "http://localhost:8000"

def test_health_check():
    """Test health check endpoint."""
    print("Testing health check...")
    response = requests.get(f"{BASE_URL}/api/health")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ Health check: {data}")
    return True

def test_siwe_auth():
    """Test SIWE authentication flow."""
    print("\nTesting SIWE authentication...")
    
    # Create a test wallet
    account = Account.create()
    wallet_address = account.address
    print(f"Test wallet: {wallet_address}")
    
    # Get nonce
    response = requests.post(f"{BASE_URL}/api/auth/nonce", params={
        "wallet_address": wallet_address
    })
    assert response.status_code == 200
    data = response.json()
    print(f"✓ Got nonce: {data['nonce']}")
    
    # Sign message
    from eth_account.messages import encode_defunct
    message = data['message']
    message_hash = encode_defunct(text=message)
    signed_message = account.sign_message(message_hash)
    signature = signed_message.signature.hex()
    
    # Verify signature
    response = requests.post(f"{BASE_URL}/api/auth/verify", params={
        "wallet_address": wallet_address,
        "signature": signature
    })
    assert response.status_code == 200
    data = response.json()
    print(f"✓ Signature verified: {data}")
    
    return wallet_address

def test_game_creation():
    """Test game creation."""
    print("\nTesting game creation...")
    
    response = requests.post(f"{BASE_URL}/api/games", params={
        "game_id": "test_game_1",
        "small_blind": 10,
        "big_blind": 20
    })
    assert response.status_code == 200
    data = response.json()
    print(f"✓ Game created: {data['game_id']}")
    
    return data['game_id']

def test_game_state(game_id):
    """Test getting game state."""
    print("\nTesting game state retrieval...")
    
    response = requests.get(f"{BASE_URL}/api/games/{game_id}")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ Game state retrieved")
    print(f"  - Stage: {data['stage']}")
    print(f"  - Players: {len(data['players'])}")
    print(f"  - Pot: {data['pot']}")
    
    return True

def test_list_games():
    """Test listing games."""
    print("\nTesting game listing...")
    
    response = requests.get(f"{BASE_URL}/api/games")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ Found {len(data['games'])} active games")
    for game in data['games']:
        print(f"  - {game['game_id']}: {game['players']} players, stage: {game['stage']}")
    
    return True

def test_withdrawal_creation(wallet_address):
    """Test withdrawal creation."""
    print("\nTesting withdrawal creation...")
    
    response = requests.post(f"{BASE_URL}/api/withdrawal/create", json={
        "wallet_address": wallet_address,
        "amount": 500
    })
    assert response.status_code == 200
    data = response.json()
    print(f"✓ Withdrawal payload created")
    print(f"  - Amount: {data['amount']}")
    print(f"  - Nonce: {data['nonce']}")
    print(f"  - Signature: {data['signature'][:20]}...")
    
    return data

def test_withdrawal_verification(payload):
    """Test withdrawal verification."""
    print("\nTesting withdrawal verification...")
    
    response = requests.post(f"{BASE_URL}/api/withdrawal/verify", json=payload)
    assert response.status_code == 200
    data = response.json()
    print(f"✓ Withdrawal verified: {data}")
    
    return True

def test_poker_logic():
    """Test poker game logic."""
    print("\nTesting poker game logic...")
    
    from arena_poker.game import Deck, HandEvaluator
    from arena_poker.models import Card, Suit, Rank, HandRank
    
    # Test deck
    deck = Deck()
    assert len(deck.cards) == 52
    print(f"✓ Deck has 52 cards")
    
    # Test hand evaluation - Royal Flush
    royal_flush = [
        Card(rank=Rank.ACE, suit=Suit.HEARTS),
        Card(rank=Rank.KING, suit=Suit.HEARTS),
        Card(rank=Rank.QUEEN, suit=Suit.HEARTS),
        Card(rank=Rank.JACK, suit=Suit.HEARTS),
        Card(rank=Rank.TEN, suit=Suit.HEARTS),
    ]
    rank, _ = HandEvaluator.evaluate_hand(royal_flush)
    assert rank == HandRank.ROYAL_FLUSH
    print(f"✓ Royal flush detected correctly")
    
    # Test hand evaluation - Pair
    pair = [
        Card(rank=Rank.ACE, suit=Suit.HEARTS),
        Card(rank=Rank.ACE, suit=Suit.SPADES),
        Card(rank=Rank.KING, suit=Suit.HEARTS),
        Card(rank=Rank.QUEEN, suit=Suit.HEARTS),
        Card(rank=Rank.JACK, suit=Suit.HEARTS),
    ]
    rank, _ = HandEvaluator.evaluate_hand(pair)
    assert rank == HandRank.PAIR
    print(f"✓ Pair detected correctly")
    
    return True

def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("Arena Poker Game Engine - Test Suite")
    print("=" * 60)
    
    try:
        # Test poker logic (doesn't require server)
        test_poker_logic()
        
        # Test API endpoints (requires server)
        print("\n" + "=" * 60)
        print("Testing API Endpoints (requires server running)")
        print("=" * 60)
        
        test_health_check()
        wallet = test_siwe_auth()
        game_id = test_game_creation()
        test_game_state(game_id)
        test_list_games()
        withdrawal_payload = test_withdrawal_creation(wallet)
        test_withdrawal_verification(withdrawal_payload)
        
        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        
    except requests.exceptions.ConnectionError:
        print("\n" + "=" * 60)
        print("⚠ Server not running. Start with: python main.py")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_all_tests()

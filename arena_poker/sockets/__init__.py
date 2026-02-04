"""Socket.IO server for real-time game communication."""

import socketio
from typing import Dict, Set
from arena_poker.models import ActionRequest, PlayerAction


class PokerSocketServer:
    """Socket.IO server for Arena Poker."""

    def __init__(self, game_manager):
        self.sio = socketio.AsyncServer(
            async_mode='asgi',
            cors_allowed_origins='*',
            logger=True,
            engineio_logger=False
        )
        self.game_manager = game_manager
        
        # Track which players are in which games
        self.game_rooms: Dict[str, Set[str]] = {}
        self.player_sessions: Dict[str, str] = {}  # sid -> wallet_address
        
        self._register_handlers()

    def _register_handlers(self):
        """Register Socket.IO event handlers."""

        @self.sio.event
        async def connect(sid, environ):
            """Handle client connection."""
            print(f"Client connected: {sid}")
            await self.sio.emit('connected', {'sid': sid}, room=sid)

        @self.sio.event
        async def disconnect(sid):
            """Handle client disconnection."""
            print(f"Client disconnected: {sid}")
            
            # Remove from player sessions
            if sid in self.player_sessions:
                wallet_address = self.player_sessions[sid]
                del self.player_sessions[sid]
                
                # Notify games about disconnection
                for game_id, players in self.game_rooms.items():
                    if wallet_address in players:
                        game = self.game_manager.get_game(game_id)
                        if game:
                            player = game.get_player(wallet_address)
                            if player:
                                player.connected = False
                            
                            await self._broadcast_game_state(game_id)

        @self.sio.event
        async def join_game(sid, data):
            """Player joins a game."""
            try:
                game_id = data.get('game_id')
                wallet_address = data.get('wallet_address')
                chips = data.get('chips', 1000)
                
                if not game_id or not wallet_address:
                    await self.sio.emit('error', {
                        'message': 'game_id and wallet_address are required'
                    }, room=sid)
                    return
                
                game = self.game_manager.get_game(game_id)
                if not game:
                    await self.sio.emit('error', {
                        'message': f'Game {game_id} not found'
                    }, room=sid)
                    return
                
                # Add player to game
                success = game.add_player(wallet_address, chips)
                if not success:
                    await self.sio.emit('error', {
                        'message': 'Could not join game (full or already joined)'
                    }, room=sid)
                    return
                
                # Track player session
                self.player_sessions[sid] = wallet_address
                
                # Add to room
                if game_id not in self.game_rooms:
                    self.game_rooms[game_id] = set()
                self.game_rooms[game_id].add(wallet_address)
                
                await self.sio.enter_room(sid, game_id)
                
                # Notify player
                await self.sio.emit('joined_game', {
                    'game_id': game_id,
                    'wallet_address': wallet_address
                }, room=sid)
                
                # Broadcast updated state
                await self._broadcast_game_state(game_id)
                
            except Exception as e:
                await self.sio.emit('error', {
                    'message': f'Error joining game: {str(e)}'
                }, room=sid)

        @self.sio.event
        async def leave_game(sid, data):
            """Player leaves a game."""
            try:
                game_id = data.get('game_id')
                wallet_address = data.get('wallet_address')
                
                if not game_id or not wallet_address:
                    return
                
                game = self.game_manager.get_game(game_id)
                if game:
                    game.remove_player(wallet_address)
                
                # Remove from room
                if game_id in self.game_rooms:
                    self.game_rooms[game_id].discard(wallet_address)
                
                await self.sio.leave_room(sid, game_id)
                
                # Notify player
                await self.sio.emit('left_game', {
                    'game_id': game_id
                }, room=sid)
                
                # Broadcast updated state
                await self._broadcast_game_state(game_id)
                
            except Exception as e:
                await self.sio.emit('error', {
                    'message': f'Error leaving game: {str(e)}'
                }, room=sid)

        @self.sio.event
        async def start_hand(sid, data):
            """Start a new hand."""
            try:
                game_id = data.get('game_id')
                
                if not game_id:
                    await self.sio.emit('error', {
                        'message': 'game_id is required'
                    }, room=sid)
                    return
                
                game = self.game_manager.get_game(game_id)
                if not game:
                    await self.sio.emit('error', {
                        'message': f'Game {game_id} not found'
                    }, room=sid)
                    return
                
                success = game.start_hand()
                if not success:
                    await self.sio.emit('error', {
                        'message': 'Cannot start hand (not enough players)'
                    }, room=sid)
                    return
                
                # Broadcast updated state
                await self._broadcast_game_state(game_id)
                
            except Exception as e:
                await self.sio.emit('error', {
                    'message': f'Error starting hand: {str(e)}'
                }, room=sid)

        @self.sio.event
        async def player_action(sid, data):
            """Handle player action."""
            try:
                game_id = data.get('game_id')
                wallet_address = data.get('wallet_address')
                action = data.get('action')
                amount = data.get('amount')
                
                if not all([game_id, wallet_address, action]):
                    await self.sio.emit('error', {
                        'message': 'game_id, wallet_address, and action are required'
                    }, room=sid)
                    return
                
                game = self.game_manager.get_game(game_id)
                if not game:
                    await self.sio.emit('error', {
                        'message': f'Game {game_id} not found'
                    }, room=sid)
                    return
                
                # Validate action
                try:
                    player_action = PlayerAction(action)
                except ValueError:
                    await self.sio.emit('error', {
                        'message': f'Invalid action: {action}'
                    }, room=sid)
                    return
                
                # Process action
                success = game.process_action(wallet_address, player_action, amount)
                if not success:
                    await self.sio.emit('error', {
                        'message': 'Invalid action or not your turn'
                    }, room=sid)
                    return
                
                # Broadcast updated state
                await self._broadcast_game_state(game_id)
                
            except Exception as e:
                await self.sio.emit('error', {
                    'message': f'Error processing action: {str(e)}'
                }, room=sid)

        @self.sio.event
        async def get_state(sid, data):
            """Get current game state."""
            try:
                game_id = data.get('game_id')
                wallet_address = data.get('wallet_address')
                
                if not game_id:
                    await self.sio.emit('error', {
                        'message': 'game_id is required'
                    }, room=sid)
                    return
                
                game = self.game_manager.get_game(game_id)
                if not game:
                    await self.sio.emit('error', {
                        'message': f'Game {game_id} not found'
                    }, room=sid)
                    return
                
                state = game.get_public_state(wallet_address)
                await self.sio.emit('game_state', state, room=sid)
                
            except Exception as e:
                await self.sio.emit('error', {
                    'message': f'Error getting state: {str(e)}'
                }, room=sid)

    async def _broadcast_game_state(self, game_id: str):
        """Broadcast game state to all players in a game."""
        game = self.game_manager.get_game(game_id)
        if not game:
            return
        
        # Send personalized state to each player individually
        if game_id in self.game_rooms:
            for wallet_address in self.game_rooms[game_id]:
                # Find the session ID for this wallet
                player_sid = None
                for sid, wa in self.player_sessions.items():
                    if wa == wallet_address:
                        player_sid = sid
                        break
                
                if player_sid:
                    state = game.get_public_state(wallet_address)
                    await self.sio.emit('game_state', state, room=player_sid)

    def get_asgi_app(self):
        """Get the ASGI application."""
        return socketio.ASGIApp(self.sio)

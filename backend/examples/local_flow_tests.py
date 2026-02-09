"""
Local Flow Tests - Multiple Agents Interacting with Docker Backend

This script creates multiple agent clients that connect to the docker backend
and interact with each other in Werewolf and Texas Hold'em games.

Agents use fixed logic (no LLM) to test game flows.

Uses only standard library - no external dependencies.
- Uses http.client for HTTP API calls
- Uses socket for WebSocket/Socket.IO connections
- Uses threading for concurrent agents
- Implements Socket.IO protocol basics for real-time communication
"""

import json
import time
import random
import base64
import hashlib
import hmac
import urllib.request
import urllib.parse
import urllib.error
import http.client
import socket
import threading
import struct
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime


# ============================================================================
# CONFIGURATION
# ============================================================================

# Backend URL (docker backend)
BACKEND_HOST = "localhost"
BACKEND_PORT = 8080
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

# Number of agents for each game
WEREWOLF_AGENTS = 6
TEXAS_AGENTS = 3


# ============================================================================
# SOCKET.IO CLIENT (Using Standard Library)
# ============================================================================

class SocketIOClient:
    """Simple Socket.IO client using standard library socket."""
    
    def __init__(self, url: str, auth_payload: Optional[Dict[str, Any]] = None):
        self.url = url
        self.auth_payload = auth_payload or {}
        self.sock: Optional[socket.socket] = None
        self.sid: Optional[str] = None
        self.connected = False
        self.event_handlers: Dict[str, List] = {}
        self.receive_thread: Optional[threading.Thread] = None
        self.running = False
    
    def connect(self):
        """Connect to Socket.IO server."""
        # Parse URL
        if self.url.startswith('ws://'):
            host_port = self.url[5:].split('/')[0]
            path = '/' + '/'.join(self.url[5:].split('/')[1:])
        elif self.url.startswith('http://'):
            host_port = self.url[7:].split('/')[0]
            path = '/socket.io/'
        else:
            raise ValueError(f"Invalid URL: {self.url}")
        
        if ':' in host_port:
            host, port = host_port.split(':')
            port = int(port)
        else:
            host = host_port
            port = 80 if self.url.startswith('http://') else 80
        
        # Perform HTTP handshake first
        conn = http.client.HTTPConnection(host, port)
        try:
            conn.request('GET', f'{path}?EIO=4&transport=polling')
            resp = conn.getresponse()
            handshake_data = resp.read().decode('utf-8')
            # Parse handshake (format: "0{"sid":"...","upgrades":[],"pingInterval":25000,"pingTimeout":60000}")
            if handshake_data.startswith('0'):
                handshake_json = json.loads(handshake_data[1:])
                self.sid = handshake_json.get('sid')
        except Exception as e:
            print(f"  Handshake error: {e}")
        finally:
            conn.close()
        
        if not self.sid:
            raise ConnectionError("Failed to get session ID")
        
        # Upgrade to WebSocket
        self._connect_websocket(host, port, path)
    
    def _connect_websocket(self, host: str, port: int, path: str):
        """Connect via WebSocket."""
        # Create WebSocket key
        key = base64.b64encode(bytes(random.getrandbits(8) for _ in range(16))).decode('utf-8')
        
        # Create socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        
        # Send WebSocket upgrade request
        upgrade_request = (
            f"GET {path}?EIO=4&transport=websocket&sid={self.sid} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self.sock.send(upgrade_request.encode('utf-8'))
        
        # Read upgrade response
        response = b''
        while b'\r\n\r\n' not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Failed to receive upgrade response")
            response += chunk
        
        response_str = response.decode('utf-8')
        if '101 Switching Protocols' not in response_str:
            raise ConnectionError(f"WebSocket upgrade failed: {response_str[:200]}")
        
        # Check if there's any data after the HTTP headers (Engine.IO open message)
        # The server might send '0{"sid":"..."}' immediately after upgrade
        header_end = response.find(b'\r\n\r\n')
        if header_end >= 0:
            remaining = response[header_end + 4:]
            if remaining:
                print(f"  [Connect] Received data after upgrade headers: {remaining.hex()}")
                # This might be an Engine.IO open message, handle it
                try:
                    message = remaining.decode('utf-8')
                    print(f"  [Connect] Message after upgrade: {message}")
                    # Handle it in receive loop instead
                except:
                    pass
        
        # Start receive thread FIRST, before sending anything
        self.running = True
        self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.receive_thread.start()
        
        # Wait a bit for thread to start
        time.sleep(0.3)
        
        # According to Socket.IO 4.x protocol, when upgrading from polling to WebSocket:
        # 1. Client sends Engine.IO PING with "probe" payload
        # 2. Server responds with Engine.IO PONG with "probe" payload
        # 3. Client sends Engine.IO UPGRADE packet (type 5)
        # 4. Then client can send Socket.IO connect (40)
        print(f"  [Connect] Sending Engine.IO ping with 'probe'...")
        self._send_packet('2probe')  # Engine.IO ping with probe
        
        # Wait for server to respond with pong
        print(f"  [Connect] Waiting for server pong...")
        time.sleep(1.0)
        
        # Send upgrade packet
        print(f"  [Connect] Sending Engine.IO upgrade packet...")
        self._send_packet('5')  # Engine.IO upgrade
        
        # Wait a bit
        time.sleep(0.5)
        
        # Now send Socket.IO connect packet (with auth payload when available)
        if self.auth_payload:
            connect_packet = '40' + json.dumps(self.auth_payload, separators=(',', ':'))
            print(f"  [Connect] Sending Socket.IO connect packet with auth payload...")
        else:
            connect_packet = '40'
            print(f"  [Connect] Sending Socket.IO connect packet '40'...")
        self._send_packet(connect_packet)  # Connect to default namespace
        
        # Wait for server to respond
        # Note: connected flag will be set when we receive '40' confirmation from server
        print(f"  [Connect] Waiting for server response (3 seconds)...")
        time.sleep(3.0)
        
        if not self.connected:
            print(f"  [Connect] Warning: Connection not confirmed by server yet")
        else:
            print(f"  [Connect] Connection confirmed by server")
    
    def _send_packet(self, packet: str):
        """Send Socket.IO packet."""
        if not self.sock:
            return
        
        # WebSocket frame: FIN=1, opcode=1 (text), masked=1 (client must mask)
        payload = packet.encode('utf-8')
        frame = bytearray([0x81])  # FIN=1, opcode=1
        
        # Generate mask
        mask = bytes(random.getrandbits(8) for _ in range(4))
        
        # Set payload length with masked bit
        if len(payload) < 126:
            frame.append(0x80 | len(payload))  # Set masked bit
        elif len(payload) < 65536:
            frame.append(0x80 | 126)  # Set masked bit
            frame.extend(struct.pack('>H', len(payload)))
        else:
            frame.append(0x80 | 127)  # Set masked bit
            frame.extend(struct.pack('>Q', len(payload)))
        
        # Add mask
        frame.extend(mask)
        
        # Mask payload
        masked_payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
        frame.extend(masked_payload)
        
        sent = self.sock.send(bytes(frame))
        print(f"  [SendPacket] Sent '{packet}' ({sent} bytes)")
    
    def _receive_loop(self):
        """Receive loop for Socket.IO messages."""
        print(f"  [ReceiveLoop] Started")
        loop_count = 0
        while self.running and self.sock:
            try:
                loop_count += 1
                if loop_count % 100 == 0:
                    print(f"  [ReceiveLoop] Still running, iteration {loop_count}")
                
                # Set socket timeout to avoid blocking forever
                self.sock.settimeout(1.0)
                
                # Read WebSocket frame header
                header = self.sock.recv(2)
                if len(header) < 2:
                    if not self.running:
                        break
                    continue
                
                fin = (header[0] >> 7) & 1
                opcode = header[0] & 0x0F
                masked = (header[1] >> 7) & 1
                payload_len = header[1] & 0x7F
                
                # Handle extended length
                if payload_len == 126:
                    len_bytes = self.sock.recv(2)
                    if len(len_bytes) < 2:
                        continue
                    payload_len = struct.unpack('>H', len_bytes)[0]
                elif payload_len == 127:
                    len_bytes = self.sock.recv(8)
                    if len(len_bytes) < 8:
                        continue
                    payload_len = struct.unpack('>Q', len_bytes)[0]
                
                # Read mask if present
                mask = None
                if masked:
                    mask_bytes = self.sock.recv(4)
                    if len(mask_bytes) < 4:
                        continue
                    mask = mask_bytes
                
                # Read payload
                payload = b''
                while len(payload) < payload_len:
                    chunk = self.sock.recv(payload_len - len(payload))
                    if not chunk:
                        break
                    payload += chunk
                
                # Unmask if needed
                if masked and mask and len(payload) == payload_len:
                    payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
                
                if opcode == 1:  # Text frame
                    try:
                        message = payload.decode('utf-8')
                        print(f"  [ReceiveLoop] ✓ Text message received: {message}")
                        self._handle_message(message)
                    except UnicodeDecodeError as e:
                        print(f"  [ReceiveLoop] Failed to decode: {e}, payload hex: {payload.hex()[:100]}")
                elif opcode == 8:  # Close frame
                    print(f"  [ReceiveLoop] Close frame received")
                    if len(payload) >= 2:
                        close_code = struct.unpack('>H', payload[:2])[0]
                        print(f"  [ReceiveLoop] Close code: {close_code}")
                    break
                elif opcode == 0:  # Continuation frame
                    pass
                elif opcode == 9:  # Ping frame (WebSocket level)
                    print(f"  [ReceiveLoop] WebSocket ping received, sending pong")
                    # Respond with pong (same payload, but we need to mask it as client)
                    pong_payload = payload
                    pong_mask = bytes(random.getrandbits(8) for _ in range(4))
                    masked_pong = bytes(pong_payload[i] ^ pong_mask[i % 4] for i in range(len(pong_payload)))
                    
                    pong_frame = bytearray([0x8A])  # FIN=1, opcode=10 (pong)
                    if len(pong_payload) < 126:
                        pong_frame.append(0x80 | len(pong_payload))  # Masked
                    elif len(pong_payload) < 65536:
                        pong_frame.append(0x80 | 126)
                        pong_frame.extend(struct.pack('>H', len(pong_payload)))
                    else:
                        pong_frame.append(0x80 | 127)
                        pong_frame.extend(struct.pack('>Q', len(pong_payload)))
                    pong_frame.extend(pong_mask)
                    pong_frame.extend(masked_pong)
                    self.sock.send(bytes(pong_frame))
                    print(f"  [ReceiveLoop] Sent pong")
                elif opcode == 10:  # Pong frame (WebSocket level)
                    print(f"  [ReceiveLoop] WebSocket pong received")
                    pass
                else:
                    print(f"  [ReceiveLoop] Unknown opcode: {opcode}, payload_len={len(payload)}")
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"  Receive error: {e}")
                    import traceback
                    traceback.print_exc()
                break
    
    def _handle_message(self, message: str):
        """Handle Socket.IO message."""
        if not message:
            return
        
        print(f"  [HandleMessage] Received Engine.IO message: '{message}' (len={len(message)})")
        
        # Engine.IO message type (first character)
        eio_type = message[0]
        socketio_data = message[1:] if len(message) > 1 else ''
        
        if eio_type == '0':  # Engine.IO open (shouldn't happen after upgrade)
            print(f"  [HandleMessage] Engine.IO open: {socketio_data}")
        elif eio_type == '1':  # Engine.IO close
            print(f"  [HandleMessage] Engine.IO close")
            self.connected = False
        elif eio_type == '2':  # Engine.IO ping
            print(f"  [HandleMessage] Engine.IO ping received, sending pong")
            self._send_packet('3')  # Engine.IO pong
        elif eio_type == '3':  # Engine.IO pong
            print(f"  [HandleMessage] Engine.IO pong received: '{socketio_data}'")
            # If it's a probe pong, we can proceed with upgrade
            if socketio_data == 'probe':
                print(f"  [HandleMessage] Received probe pong, upgrade can proceed")
        elif eio_type == '4':  # Engine.IO message (contains Socket.IO packet)
            print(f"  [HandleMessage] Engine.IO message (Socket.IO packet): '{socketio_data}'")
            # Parse Socket.IO packet
            if not socketio_data:
                return
            
            socketio_type = socketio_data[0]
            socketio_payload = socketio_data[1:] if len(socketio_data) > 1 else ''
            
            if socketio_type == '0':  # Socket.IO connect
                print(f"  [HandleMessage] Socket.IO connect confirmed! Payload: '{socketio_payload}'")
                # Parse sid from payload if present (format: '{"sid":"..."}')
                if socketio_payload:
                    try:
                        sid_data = json.loads(socketio_payload)
                        if 'sid' in sid_data:
                            self.sid = sid_data['sid']
                            print(f"  [HandleMessage] Updated SID: {self.sid}")
                    except:
                        pass
                # Set connected flag NOW, before emitting connect event
                # This ensures emit() works in event handlers
                self.connected = True
                # Connect confirmed - trigger connect event
                self._emit('connect', {})
            elif socketio_type == '1':  # Socket.IO disconnect
                print(f"  [HandleMessage] Socket.IO disconnect")
                self.connected = False
            elif socketio_type == '2':  # Socket.IO event
                print(f"  [HandleMessage] Socket.IO event: '{socketio_payload[:100]}'")
                try:
                    event_data = json.loads(socketio_payload)
                    event_name = event_data[0]
                    event_args = event_data[1] if len(event_data) > 1 else {}
                    print(f"  [HandleMessage] Emitting event '{event_name}' with args: {event_args}")
                    # If this is the 'connected' event, set connected flag so emit() works
                    if event_name == 'connected':
                        self.connected = True
                        print(f"  [HandleMessage] Set connected=True due to 'connected' event")
                    self._emit(event_name, event_args)
                except Exception as e:
                    print(f"  Error parsing event: {e}, data: {socketio_payload[:100]}")
            elif socketio_type == '3':  # Socket.IO ack
                print(f"  [HandleMessage] Socket.IO ack")
            elif socketio_type == '4':  # Socket.IO error
                print(f"Socket.IO error: {socketio_payload}")
            elif socketio_type == '5':  # Socket.IO binary event
                print(f"  [HandleMessage] Socket.IO binary event")
            elif socketio_type == '6':  # Socket.IO binary ack
                print(f"  [HandleMessage] Socket.IO binary ack")
        elif eio_type == '5':  # Engine.IO upgrade
            print(f"  [HandleMessage] Engine.IO upgrade")
        elif eio_type == '6':  # Engine.IO noop (used during upgrade)
            print(f"  [HandleMessage] Engine.IO noop (upgrade confirmation)")
        else:
            print(f"  [HandleMessage] Unknown Engine.IO type: '{eio_type}'")
    
    def _emit(self, event_name: str, data: Any):
        """Emit event to handlers."""
        if event_name in self.event_handlers:
            for handler in self.event_handlers[event_name]:
                try:
                    handler(data)
                except Exception as e:
                    print(f"Handler error for {event_name}: {e}")
    
    def on(self, event: str, handler):
        """Register event handler."""
        if event not in self.event_handlers:
            self.event_handlers[event] = []
        self.event_handlers[event].append(handler)
    
    def emit(self, event: str, data: Any = None):
        """Emit event to server."""
        if not self.connected:
            return
        
        packet_data = json.dumps([event, data])
        self._send_packet('42' + packet_data)
    
    def disconnect(self):
        """Disconnect from server."""
        self.running = False
        if self.sock:
            self._send_packet('41')  # Disconnect
            self.sock.close()
        self.connected = False


# ============================================================================
# HTTP CLIENT HELPERS
# ============================================================================

def http_request(method: str, path: str, params: Optional[Dict] = None, 
                 data: Optional[Dict] = None, headers: Optional[Dict] = None) -> Dict:
    """Make HTTP request using standard library."""
    conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=10)
    
    try:
        # Build URL with params
        url = path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        
        # Prepare headers
        req_headers = {'Content-Type': 'application/json'}
        if headers:
            req_headers.update(headers)
        
        # Prepare body
        body = None
        if data:
            body = json.dumps(data).encode('utf-8')
        
        # Make request
        conn.request(method, url, body, req_headers)
        response = conn.getresponse()
        
        # Read response
        response_data = response.read().decode('utf-8')
        
        # Parse JSON if possible
        try:
            result = json.loads(response_data) if response_data else {}
        except json.JSONDecodeError:
            result = {'raw': response_data}
        
        result['status_code'] = response.status
        return result
        
    except Exception as e:
        return {'error': str(e), 'status_code': 0}
    finally:
        conn.close()


# ============================================================================
# AGENT CLASSES
# ============================================================================

@dataclass
class AgentState:
    """State tracking for an agent."""
    player_name: str
    nickname: str
    player_id: Optional[str] = None
    address: Optional[str] = None
    authenticated: bool = False
    game_id: Optional[str] = None
    game_type: Optional[str] = None
    game_state: Optional[Dict] = None
    my_role: Optional[Dict] = None
    my_hole_cards: Optional[List[str]] = None
    is_my_turn: bool = False
    events_received: List[tuple] = field(default_factory=list)
    sid: Optional[str] = None
    fingerprint: Optional[str] = None
    bot_token: Optional[str] = None


class BaseAgent:
    """Base agent class with common functionality."""
    
    def __init__(self, player_name: str, nickname: str, address: Optional[str] = None):
        self.state = AgentState(player_name=player_name, nickname=nickname, address=address)
        self.state.fingerprint = f"local-flow-{nickname.lower()}"
        self.sio: Optional[SocketIOClient] = None

    def fetch_bot_token(self) -> bool:
        """Fetch anti-bot token for Socket.IO auth (required in non-local mode)."""
        if not self.state.fingerprint:
            return False

        result = http_request(
            'POST',
            '/bot/token',
            data={'fingerprint': self.state.fingerprint},
            headers={
                'User-Agent': f'agent-local-flow/{self.state.nickname}',
                'x-agent-id': self.state.nickname,
            },
        )

        token = result.get('token')
        if token:
            self.state.bot_token = token
            return True

        # In LOCAL_DEBUG_MODE with bypass enabled, token may not be required.
        print(f"[{self.state.nickname}] Token fetch skipped/failed: {result}")
        return False
    
    def register(self) -> bool:
        """Register the agent."""
        result = http_request('POST', '/api/register', params={
            'player_name': self.state.player_name,
            'address': self.state.address,
        })
        if result.get('status_code') != 200:
            return False
        user = result.get('user') or {}
        player_id = user.get('player_id')
        if not player_id:
            return False
        self.state.player_id = player_id
        self.state.player_name = user.get('player_name') or self.state.player_name
        return True
    
    def login(self) -> bool:
        """Login the agent."""
        if not self.state.player_id:
            return False
        result = http_request('POST', '/api/login', params={
            'player_id': self.state.player_id
        })
        return result.get('status_code') == 200
    
    def connect_socket(self):
        """Connect Socket.IO client."""
        # Try token flow first for compatibility with anti-bot auth.
        self.fetch_bot_token()

        auth_payload = {
            'fingerprint': self.state.fingerprint,
            'agent_id': self.state.nickname,
        }
        if self.state.bot_token:
            auth_payload['botToken'] = self.state.bot_token

        self.sio = SocketIOClient(BACKEND_URL, auth_payload=auth_payload)
        
        # Setup handlers before connecting
        def on_connected(data):
            print(f"[{self.state.nickname}] Received 'connected' event, authenticating...")
            # Send authenticate immediately
            self.sio.emit('authenticate', {
                'login_key': self.state.player_id,
                'player_id': self.state.player_id,  # Backward compatibility
            })
        
        def on_connect(data):
            print(f"[{self.state.nickname}] Socket.IO connect confirmed")
            # This is triggered when we receive '40' from server
        
        def on_authenticated(data):
            print(f"[{self.state.nickname}] ✓ Authenticated")
            self.state.authenticated = True
            self.state.sid = self.sio.sid
        
        def on_error(data):
            print(f"[{self.state.nickname}] ✗ Error: {data}")
            self.state.events_received.append(('error', data))
        
        def on_snapshot(data):
            print(f"[{self.state.nickname}] Received GAME_SNAPSHOT")
            self.state.game_state = data
            self.state.game_id = data.get('game_id')
            self.state.game_type = data.get('game_type')
            if 'your_role' in data:
                self.state.my_role = data.get('your_role')
            self.state.events_received.append(('GAME_SNAPSHOT', data))
            self.on_game_snapshot(data)
        
        self.sio.on('connected', on_connected)  # Server sends this on connect
        self.sio.on('connect', on_connect)  # Socket.IO namespace connect
        self.sio.on('authenticated', on_authenticated)
        self.sio.on('error', on_error)
        self.sio.on('GAME_SNAPSHOT', on_snapshot)
        
        self.sio.connect()
    
    def disconnect_socket(self):
        """Disconnect Socket.IO client."""
        if self.sio:
            self.sio.disconnect()
            self.sio = None
    
    def on_game_snapshot(self, data: Dict):
        """Handle game snapshot - override in subclasses."""
        pass


class WerewolfAgent(BaseAgent):
    """Agent for Werewolf game with fixed logic."""
    
    def __init__(self, player_name: str, nickname: str, address: Optional[str] = None):
        super().__init__(player_name, nickname, address)
        self.last_phase = None
    
    def connect_socket(self):
        """Connect and setup werewolf handlers."""
        super().connect_socket()
        
        def on_joined(data):
            print(f"[{self.state.nickname}] Joined werewolf game")
            self.state.events_received.append(('werewolf_joined', data))
        
        def on_state(data):
            print(f"[{self.state.nickname}] Received werewolf_state")
            self.state.game_state = data
            self.state.events_received.append(('werewolf_state', data))
            self.decide_action()
        
        def on_phase_change(data):
            print(f"[{self.state.nickname}] Phase changed: {data.get('phase')}")
            self.last_phase = data.get('phase')
            self.state.events_received.append(('werewolf_phase_change', data))
            self.decide_action()
        
        def on_game_created(data):
            print(f"[{self.state.nickname}] Game created: {data.get('game_id')}")
            self.state.events_received.append(('werewolf_game_created', data))
        
        self.sio.on('werewolf_joined', on_joined)
        self.sio.on('werewolf_state', on_state)
        self.sio.on('werewolf_phase_change', on_phase_change)
        self.sio.on('werewolf_game_created', on_game_created)
    
    def create_game(self, game_id: str):
        """Create a werewolf game."""
        if self.sio:
            self.sio.emit('create_werewolf_game', {'game_id': game_id})
    
    def join_game(self, game_id: str):
        """Join a werewolf game."""
        if self.sio:
            self.sio.emit('join_werewolf_game', {
                'game_id': game_id,
                'nickname': self.state.nickname
            })
    
    def start_game(self, game_id: str):
        """Start the werewolf game."""
        if self.sio:
            self.sio.emit('start_werewolf_game', {'game_id': game_id})
    
    def decide_action(self):
        """Decide action based on current game state."""
        if not self.state.game_state:
            return
        
        phase = self.state.game_state.get('phase')
        if not phase:
            return
        
        # Get my role info
        if not self.state.my_role and self.state.game_state.get('players'):
            for player in self.state.game_state['players']:
                if (player.get('wallet_address') == self.state.player_id or 
                    player.get('nickname') == self.state.nickname):
                    if 'role' in player and player['role']:
                        self.state.my_role = player['role']
                    break
        
        # Fixed logic based on phase
        if phase == 'night_wolf_discussion':
            self._handle_wolf_discussion()
        elif phase == 'night_wolf_voting':
            self._handle_wolf_voting()
        elif phase == 'night_seer':
            self._handle_seer_action()
        elif phase == 'night_witch':
            self._handle_witch_action()
        elif phase == 'day_speaking':
            self._handle_speaking()
        elif phase == 'day_voting':
            self._handle_voting()
    
    def _handle_wolf_discussion(self):
        """Handle wolf discussion phase."""
        if not self.state.my_role or not self.sio:
            return
        
        role_type = self.state.my_role.get('role_type')
        if role_type == 'wolf':
            self.sio.emit('werewolf_action', {
                'game_id': self.state.game_id,
                'action': 'wolf_chat',
                'message': f'{self.state.nickname}: Let\'s kill someone!'
            })
    
    def _handle_wolf_voting(self):
        """Handle wolf voting phase."""
        if not self.state.my_role or not self.sio:
            return
        
        role_type = self.state.my_role.get('role_type')
        if role_type == 'wolf':
            if self.state.game_state and self.state.game_state.get('players'):
                non_wolves = [
                    p for p in self.state.game_state['players']
                    if p.get('is_alive') and p.get('role', {}).get('role_type') != 'wolf'
                ]
                if non_wolves:
                    target = random.choice(non_wolves)
                    self.sio.emit('werewolf_action', {
                        'game_id': self.state.game_id,
                        'action': 'night_kill',
                        'target_sid': target.get('sid')
                    })
                    print(f"[{self.state.nickname}] Voted to kill {target.get('nickname')}")
    
    def _handle_seer_action(self):
        """Handle seer check phase."""
        if not self.state.my_role or not self.sio:
            return
        
        role_type = self.state.my_role.get('role_type')
        if role_type == 'seer':
            if self.state.game_state and self.state.game_state.get('players'):
                others = [
                    p for p in self.state.game_state['players']
                    if p.get('is_alive') and p.get('sid') != self.state.sid
                ]
                if others:
                    target = random.choice(others)
                    self.sio.emit('werewolf_action', {
                        'game_id': self.state.game_id,
                        'action': 'seer_check',
                        'target_sid': target.get('sid')
                    })
                    print(f"[{self.state.nickname}] Checking {target.get('nickname')}")
    
    def _handle_witch_action(self):
        """Handle witch action phase."""
        if not self.state.my_role or not self.sio:
            return
        
        role_type = self.state.my_role.get('role_type')
        if role_type == 'witch':
            self.sio.emit('werewolf_action', {
                'game_id': self.state.game_id,
                'action': 'witch_skip'
            })
            print(f"[{self.state.nickname}] Witch skipping action")
    
    def _handle_speaking(self):
        """Handle day speaking phase."""
        if not self.state.game_state or not self.sio:
            return
        
        current_speaker = self.state.game_state.get('current_speaker')
        speaking_order = self.state.game_state.get('speaking_order', [])
        current_speaker_index = self.state.game_state.get('current_speaker_index', 0)
        
        if speaking_order and current_speaker_index < len(speaking_order):
            my_sid = None
            for player in self.state.game_state.get('players', []):
                if (player.get('wallet_address') == self.state.player_id or 
                    player.get('nickname') == self.state.nickname):
                    my_sid = player.get('sid')
                    break
            
            if my_sid and speaking_order[current_speaker_index] == my_sid:
                self.sio.emit('werewolf_action', {
                    'game_id': self.state.game_id,
                    'action': 'speak',
                    'message': f'{self.state.nickname}: I think we should vote carefully.'
                })
                print(f"[{self.state.nickname}] Speaking")
    
    def _handle_voting(self):
        """Handle day voting phase."""
        if not self.state.game_state or not self.sio:
            return
        
        if self.state.game_state.get('players'):
            others = [
                p for p in self.state.game_state['players']
                if p.get('is_alive') and p.get('sid') != self.state.sid
            ]
            if others and random.random() > 0.3:
                target = random.choice(others)
                self.sio.emit('werewolf_action', {
                    'game_id': self.state.game_id,
                    'action': 'vote',
                    'target_sid': target.get('sid')
                })
                print(f"[{self.state.nickname}] Voted for {target.get('nickname')}")
            else:
                self.sio.emit('werewolf_action', {
                    'game_id': self.state.game_id,
                    'action': 'vote',
                    'target_sid': None
                })
                print(f"[{self.state.nickname}] Abstained")


class TexasAgent(BaseAgent):
    """Agent for Texas Hold'em game with fixed logic."""
    
    def connect_socket(self):
        """Connect and setup texas handlers."""
        super().connect_socket()
        
        def on_joined(data):
            print(f"[{self.state.nickname}] Joined poker table")
            self.state.events_received.append(('joined_game', data))
        
        def on_game_update(data):
            print(f"[{self.state.nickname}] Received game_update")
            self.state.game_state = data
            self.state.game_id = data.get('game_id')
            self.state.events_received.append(('game_update', data))
            self.decide_action()
        
        def on_private_hand(data):
            print(f"[{self.state.nickname}] Received private_hand")
            self.state.my_hole_cards = data.get('hole_cards')
            self.state.is_my_turn = data.get('your_turn', False)
            self.state.events_received.append(('private_hand', data))
            if self.state.is_my_turn:
                self.decide_action()
        
        self.sio.on('joined_game', on_joined)
        self.sio.on('game_update', on_game_update)
        self.sio.on('private_hand', on_private_hand)
    
    def join_table(self, table_id: str, chips: int = 1000):
        """Join a poker table."""
        if self.sio:
            self.sio.emit('join_game', {
                'table_id': table_id,
                'chips': chips
            })
    
    def start_hand(self, table_id: str):
        """Start a new hand."""
        if self.sio:
            self.sio.emit('start_hand', {'table_id': table_id})
    
    def decide_action(self):
        """Decide poker action based on current state."""
        if not self.state.is_my_turn or not self.sio:
            return
        
        if not self.state.game_state:
            return
        
        current_bet = self.state.game_state.get('current_bet', 0)
        
        # Get my player info
        my_player = None
        if self.state.game_state.get('players'):
            for player in self.state.game_state['players']:
                if (player.get('wallet_address') == self.state.player_id or 
                    player.get('nickname') == self.state.nickname):
                    my_player = player
                    break
        
        if not my_player:
            return
        
        my_chips = my_player.get('chips', 0)
        my_current_bet = my_player.get('current_bet', 0)
        to_call = current_bet - my_current_bet
        
        # Simple strategy
        if to_call == 0:
            self.sio.emit('player_move', {
                'table_id': self.state.game_id,
                'action': 'check',
                'message': f'{self.state.nickname}: Checking.'
            })
            print(f"[{self.state.nickname}] Checking")
        elif to_call <= my_chips * 0.2:
            self.sio.emit('player_move', {
                'table_id': self.state.game_id,
                'action': 'call',
                'message': f'{self.state.nickname}: Calling {to_call}.'
            })
            print(f"[{self.state.nickname}] Calling {to_call}")
        else:
            self.sio.emit('player_move', {
                'table_id': self.state.game_id,
                'action': 'fold',
                'message': f'{self.state.nickname}: Folding, too expensive.'
            })
            print(f"[{self.state.nickname}] Folding")


# ============================================================================
# TEST FUNCTIONS
# ============================================================================

def register_and_login_agents(agents: List[BaseAgent]):
    """Register and login all agents."""
    print("\n=== Registering and Logging in Agents ===")
    for agent in agents:
        try:
            registered = agent.register()
            if not registered:
                print(f"  Registration failed: {agent.state.nickname}")
                continue
            print(f"  Registered: {agent.state.nickname} -> {agent.state.player_id}")

            logged_in = agent.login()
            if not logged_in:
                print(f"  Login failed: {agent.state.nickname} ({agent.state.player_id})")
                continue
            print(f"  Logged in: {agent.state.nickname} ({agent.state.player_id})")
        except Exception as e:
            print(f"  Error with {agent.state.nickname}: {e}")


def test_werewolf_flow():
    """Test werewolf game flow with multiple agents."""
    print("\n" + "="*70)
    print("TESTING WEREWOLF GAME FLOW")
    print("="*70)
    
    # Create agents
    agents = [
        WerewolfAgent(player_name=f"WerewolfAgent{i+1}", nickname=f"WerewolfAgent{i+1}")
        for i in range(WEREWOLF_AGENTS)
    ]
    
    # Register and login
    register_and_login_agents(agents)
    
    # Connect all agents
    print("\n=== Connecting Agents ===")
    for agent in agents:
        try:
            agent.connect_socket()
            time.sleep(0.2)  # Wait for connection
        except Exception as e:
            print(f"  Error connecting {agent.state.nickname}: {e}")
    
    # Wait for authentication
    time.sleep(2)
    
    # Create game with first agent
    game_id = "test_werewolf_1"
    print(f"\n=== Creating Game: {game_id} ===")
    agents[0].create_game(game_id)
    time.sleep(0.5)
    
    # All agents join
    print(f"\n=== Joining Game ===")
    for agent in agents:
        agent.join_game(game_id)
        time.sleep(0.1)
    
    time.sleep(1)
    
    # Start game
    print(f"\n=== Starting Game ===")
    agents[0].start_game(game_id)
    time.sleep(1)
    
    # Let game run for a while
    print(f"\n=== Running Game (30 seconds) ===")
    time.sleep(30)
    
    # Disconnect all agents
    print(f"\n=== Disconnecting Agents ===")
    for agent in agents:
        agent.disconnect_socket()
    
    print("\n✓ Werewolf flow test completed")


def test_texas_flow():
    """Test Texas Hold'em game flow with multiple agents."""
    print("\n" + "="*70)
    print("TESTING TEXAS HOLD'EM GAME FLOW")
    print("="*70)
    
    # Create agents
    agents = [
        TexasAgent(player_name=f"TexasAgent{i+1}", nickname=f"TexasAgent{i+1}")
        for i in range(TEXAS_AGENTS)
    ]
    
    # Register and login
    register_and_login_agents(agents)
    
    # Connect all agents
    print("\n=== Connecting Agents ===")
    for agent in agents:
        try:
            agent.connect_socket()
            time.sleep(0.2)
        except Exception as e:
            print(f"  Error connecting {agent.state.nickname}: {e}")
    
    # Wait for authentication
    time.sleep(2)
    
    # All agents join table
    table_id = "test_texas_1"
    print(f"\n=== Joining Table: {table_id} ===")
    for agent in agents:
        agent.join_table(table_id, chips=1000)
        time.sleep(0.1)
    
    time.sleep(1)
    
    # Start hand
    print(f"\n=== Starting Hand ===")
    agents[0].start_hand(table_id)
    time.sleep(1)
    
    # Let game run for a while
    print(f"\n=== Running Game (20 seconds) ===")
    time.sleep(20)
    
    # Disconnect all agents
    print(f"\n=== Disconnecting Agents ===")
    for agent in agents:
        agent.disconnect_socket()
    
    print("\n✓ Texas Hold'em flow test completed")


def check_backend_health():
    """Check if backend is running."""
    try:
        result = http_request('GET', '/health')
        if result.get('status_code') == 200:
            print(f"✓ Backend is healthy: {result}")
            return True
        else:
            print(f"✗ Backend returned status {result.get('status_code')}")
            return False
    except Exception as e:
        print(f"✗ Backend not reachable: {e}")
        print(f"  Make sure docker backend is running on {BACKEND_URL}")
        return False


def main():
    """Main test runner."""
    print("="*70)
    print("LOCAL FLOW TESTS - Multiple Agents Interacting (Real Socket.IO)")
    print("="*70)
    
    # Check backend health
    if not check_backend_health():
        print("\n⚠️  Backend not available. Please start docker backend first:")
        print("   docker compose -f docker-compose.yml up")
        return
    
    try:
        # Test werewolf flow
        test_werewolf_flow()
        
        # Wait a bit between tests
        time.sleep(2)
        
        # Test texas flow
        test_texas_flow()
        
        print("\n" + "="*70)
        print("ALL TESTS COMPLETED")
        print("="*70)
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

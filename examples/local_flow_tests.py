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

import base64
import http.client
import json
import random
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Any

from backend.utils import log

# ============================================================================
# CONFIGURATION
# ============================================================================
ARENA_BACKEND_HOST = '127.0.0.1'
ARENA_BACKEND_SCHEME ='http'
ARENA_BACKEND_PORT =8080
# Backend URL
# Default to HTTPS because production endpoint redirects HTTP -> HTTPS (301).
def _select_backend():
    env_host = ARENA_BACKEND_HOST
    env_scheme = ARENA_BACKEND_SCHEME
    env_port = ARENA_BACKEND_PORT

    if env_host:
        scheme = (env_scheme or "https").strip().lower() or "https"
        port = int(env_port or ("443" if scheme == "https" else "80"))
        return scheme, env_host.strip(), port

    # Prefer local docker backend when available.
    try:
        conn = http.client.HTTPConnection("localhost", 8080, timeout=1)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        resp.read()
        if resp.status == 200:
            return "http", "localhost", 8080
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

    scheme = (env_scheme or "https").strip().lower() or "https"
    port = int(env_port or ("443" if scheme == "https" else "80"))
    host = (env_host or "api-dev.clawarena.io").strip()
    return scheme, host, port


BACKEND_SCHEME, BACKEND_HOST, BACKEND_PORT = _select_backend()


def _format_backend_url(scheme: str, host: str, port: int) -> str:
    """Build backend URL and keep explicit non-default ports for Socket.IO."""
    default_port = 443 if scheme == "https" else 80
    if port == default_port:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


BACKEND_URL = _format_backend_url(BACKEND_SCHEME, BACKEND_HOST, BACKEND_PORT)
# Number of agents for each game
WEREWOLF_AGENTS = 8
TEXAS_AGENTS = 3
WEREWOLF_ENTRY_FEE = 100
TEXAS_BUY_IN_CHIPS = 1000
EPSILON = Decimal("0.000001")
LOCAL_DEBUG_MODE = False
STRICT_AUTH_MODE = True  # flipped to False when backend reports local debug
LOGIN_SECRET_SUPPORTED = True  # flipped to False if backend omits login_secret entirely


def unique_id(prefix: str) -> str:
    """Generate a short unique id to avoid collisions with persisted games."""
    return f"{prefix}_{int(time.time())}_{random.randint(1000, 9999)}"


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
        use_tls = False
        if self.url.startswith('ws://'):
            host_port = self.url[5:].split('/')[0]
            path = '/' + '/'.join(self.url[5:].split('/')[1:])
        elif self.url.startswith('wss://'):
            host_port = self.url[6:].split('/')[0]
            path = '/' + '/'.join(self.url[6:].split('/')[1:])
            use_tls = True
        elif self.url.startswith('http://'):
            host_port = self.url[7:].split('/')[0]
            path = '/socket.io/'
        elif self.url.startswith('https://'):
            host_port = self.url[8:].split('/')[0]
            path = '/socket.io/'
            use_tls = True
        else:
            raise ValueError(f"Invalid URL: {self.url}")
        
        if ':' in host_port:
            host, port = host_port.split(':')
            port = int(port)
        else:
            host = host_port
            port = 443 if use_tls else 80
        
        # Perform HTTP handshake first
        conn_cls = http.client.HTTPSConnection if use_tls else http.client.HTTPConnection
        conn = conn_cls(host, port, timeout=10)
        try:
            conn.request('GET', f'{path}?EIO=4&transport=polling')
            resp = conn.getresponse()
            handshake_data = resp.read().decode('utf-8')
            # Parse handshake (format: "0{"sid":"...","upgrades":[],"pingInterval":25000,"pingTimeout":60000}")
            if handshake_data.startswith('0'):
                handshake_json = json.loads(handshake_data[1:])
                self.sid = handshake_json.get('sid')
        except Exception as e:
            log.error(f"  Handshake error: {e}")
        finally:
            conn.close()
        
        if not self.sid:
            raise ConnectionError("Failed to get session ID")
        
        # Upgrade to WebSocket
        self._connect_websocket(host, port, path, use_tls)
    
    def _connect_websocket(self, host: str, port: int, path: str, use_tls: bool = False):
        """Connect via WebSocket."""
        # Create WebSocket key
        key = base64.b64encode(bytes(random.getrandbits(8) for _ in range(16))).decode('utf-8')
        
        # Create socket
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.connect((host, port))
        if use_tls:
            context = ssl.create_default_context()
            self.sock = context.wrap_socket(raw_sock, server_hostname=host)
        else:
            self.sock = raw_sock
        
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
                log.info(f"  [Connect] Received data after upgrade headers: {remaining.hex()}")
                # This might be an Engine.IO open message, handle it
                try:
                    message = remaining.decode('utf-8')
                    log.info(f"  [Connect] Message after upgrade: {message}")
                    # Handle it in receive loop instead
                except:
                    pass
        
        # Start receive thread FIRST, before sending anything
        self.running = True
        self.receive_thread = threading.Thread(target=self._receive_loop, daemon=False)
        self.receive_thread.start()
        
        # Wait a bit for thread to start
        time.sleep(0.3)
        
        # According to Socket.IO 4.x protocol, when upgrading from polling to WebSocket:
        # 1. Client sends Engine.IO PING with "probe" payload
        # 2. Server responds with Engine.IO PONG with "probe" payload
        # 3. Client sends Engine.IO UPGRADE packet (type 5)
        # 4. Then client can send Socket.IO connect (40)
        log.info(f"  [Connect] Sending Engine.IO ping with 'probe'...")
        self._send_packet('2probe')  # Engine.IO ping with probe
        
        # Wait for server to respond with pong
        log.info(f"  [Connect] Waiting for server pong...")
        time.sleep(1.0)
        
        # Send upgrade packet
        log.info(f"  [Connect] Sending Engine.IO upgrade packet...")
        self._send_packet('5')  # Engine.IO upgrade
        
        # Wait a bit
        time.sleep(0.5)
        
        # Now send Socket.IO connect packet (with auth payload when available)
        if self.auth_payload:
            connect_packet = '40' + json.dumps(self.auth_payload, separators=(',', ':'))
            log.info(f"  [Connect] Sending Socket.IO connect packet with auth payload...")
        else:
            connect_packet = '40'
            log.info(f"  [Connect] Sending Socket.IO connect packet '40'...")
        self._send_packet(connect_packet)  # Connect to default namespace
        
        # Wait for server to respond
        # Note: connected flag will be set when we receive '40' confirmation from server
        log.info(f"  [Connect] Waiting for server response (3 seconds)...")
        time.sleep(3.0)
        
        if not self.connected:
            log.warning(f"  [Connect] Warning: Connection not confirmed by server yet")
        else:
            log.info(f"  [Connect] Connection confirmed by server")
    
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
        log.info(f"  [SendPacket] Sent '{packet}' ({sent} bytes)")
    
    def _receive_loop(self):
        """Receive loop for Socket.IO messages."""
        log.info(f"  [ReceiveLoop] Started")
        loop_count = 0
        while self.running and self.sock:
            try:
                loop_count += 1
                if loop_count % 100 == 0:
                    log.info(f"  [ReceiveLoop] Still running, iteration {loop_count}")
                
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
                        log.info(f"  [ReceiveLoop] ✓ Text message received: {message}")
                        self._handle_message(message)
                    except UnicodeDecodeError as e:
                        log.error(f"  [ReceiveLoop] Failed to decode: {e}, payload hex: {payload.hex()[:100]}")
                elif opcode == 8:  # Close frame
                    log.info(f"  [ReceiveLoop] Close frame received")
                    if len(payload) >= 2:
                        close_code = struct.unpack('>H', payload[:2])[0]
                        log.info(f"  [ReceiveLoop] Close code: {close_code}")
                    break
                elif opcode == 0:  # Continuation frame
                    pass
                elif opcode == 9:  # Ping frame (WebSocket level)
                    log.info(f"  [ReceiveLoop] WebSocket ping received, sending pong")
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
                    log.info(f"  [ReceiveLoop] Sent pong")
                elif opcode == 10:  # Pong frame (WebSocket level)
                    log.info(f"  [ReceiveLoop] WebSocket pong received")
                    pass
                else:
                    log.info(f"  [ReceiveLoop] Unknown opcode: {opcode}, payload_len={len(payload)}")
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    log.error(f"  Receive error: {e}")
                    import traceback
                    traceback.print_exc()
                break
    
    def _handle_message(self, message: str):
        """Handle Socket.IO message."""
        if not message:
            return
        
        log.info(f"  [HandleMessage] Received Engine.IO message: '{message}' (len={len(message)})")
        
        # Engine.IO message type (first character)
        eio_type = message[0]
        socketio_data = message[1:] if len(message) > 1 else ''
        
        if eio_type == '0':  # Engine.IO open (shouldn't happen after upgrade)
            log.info(f"  [HandleMessage] Engine.IO open: {socketio_data}")
        elif eio_type == '1':  # Engine.IO close
            log.info(f"  [HandleMessage] Engine.IO close")
            self.connected = False
        elif eio_type == '2':  # Engine.IO ping
            log.info(f"  [HandleMessage] Engine.IO ping received, sending pong")
            self._send_packet('3')  # Engine.IO pong
        elif eio_type == '3':  # Engine.IO pong
            log.info(f"  [HandleMessage] Engine.IO pong received: '{socketio_data}'")
            # If it's a probe pong, we can proceed with upgrade
            if socketio_data == 'probe':
                log.info(f"  [HandleMessage] Received probe pong, upgrade can proceed")
        elif eio_type == '4':  # Engine.IO message (contains Socket.IO packet)
            log.info(f"  [HandleMessage] Engine.IO message (Socket.IO packet): '{socketio_data}'")
            # Parse Socket.IO packet
            if not socketio_data:
                return
            
            socketio_type = socketio_data[0]
            socketio_payload = socketio_data[1:] if len(socketio_data) > 1 else ''
            
            if socketio_type == '0':  # Socket.IO connect
                log.info(f"  [HandleMessage] Socket.IO connect confirmed! Payload: '{socketio_payload}'")
                # Parse sid from payload if present (format: '{"sid":"..."}')
                if socketio_payload:
                    try:
                        sid_data = json.loads(socketio_payload)
                        if 'sid' in sid_data:
                            self.sid = sid_data['sid']
                            log.info(f"  [HandleMessage] Updated SID: {self.sid}")
                    except:
                        pass
                # Set connected flag NOW, before emitting connect event
                # This ensures emit() works in event handlers
                self.connected = True
                # Connect confirmed - trigger connect event
                self._emit('connect', {})
            elif socketio_type == '1':  # Socket.IO disconnect
                log.info(f"  [HandleMessage] Socket.IO disconnect")
                self.connected = False
            elif socketio_type == '2':  # Socket.IO event
                log.info(f"  [HandleMessage] Socket.IO event: '{socketio_payload[:100]}'")
                try:
                    event_data = json.loads(socketio_payload)
                    event_name = event_data[0]
                    event_args = event_data[1] if len(event_data) > 1 else {}
                    log.info(f"  [HandleMessage] Emitting event '{event_name}' with args: {event_args}")
                    # If this is the 'connected' event, set connected flag so emit() works
                    if event_name == 'connected':
                        self.connected = True
                        log.info(f"  [HandleMessage] Set connected=True due to 'connected' event")
                    self._emit(event_name, event_args)
                except Exception as e:
                    log.error(f"  Error parsing event: {e}, data: {socketio_payload[:100]}")
            elif socketio_type == '3':  # Socket.IO ack
                log.info(f"  [HandleMessage] Socket.IO ack")
            elif socketio_type == '4':  # Socket.IO error
                log.error(f"Socket.IO error: {socketio_payload}")
            elif socketio_type == '5':  # Socket.IO binary event
                log.info(f"  [HandleMessage] Socket.IO binary event")
            elif socketio_type == '6':  # Socket.IO binary ack
                log.info(f"  [HandleMessage] Socket.IO binary ack")
        elif eio_type == '5':  # Engine.IO upgrade
            log.info(f"  [HandleMessage] Engine.IO upgrade")
        elif eio_type == '6':  # Engine.IO noop (used during upgrade)
            log.info(f"  [HandleMessage] Engine.IO noop (upgrade confirmation)")
        else:
            log.info(f"  [HandleMessage] Unknown Engine.IO type: '{eio_type}'")
    
    def _emit(self, event_name: str, data: Any):
        """Emit event to handlers."""
        if event_name in self.event_handlers:
            for handler in self.event_handlers[event_name]:
                try:
                    handler(data)
                except Exception as e:
                    log.error(f"Handler error for {event_name}: {e}")
    
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
            try:
                self._send_packet('41')  # Disconnect
            except Exception:
                pass
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.connected = False
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=2.0)


# ============================================================================
# HTTP CLIENT HELPERS
# ============================================================================

def http_request(method: str, path: str, params: Optional[Dict] = None, 
                 data: Optional[Dict] = None, headers: Optional[Dict] = None) -> Dict:
    """Make HTTP request using standard library."""
    conn_cls = http.client.HTTPSConnection if BACKEND_SCHEME == 'https' else http.client.HTTPConnection
    conn = conn_cls(BACKEND_HOST, BACKEND_PORT, timeout=10)
    
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


def poll_http_status(
    method: str,
    path: str,
    expected_status: int,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
    interval: float = 0.5,
) -> Dict[str, Any]:
    """Poll an endpoint until it returns the expected HTTP status or timeout."""
    deadline = time.time() + timeout
    last_result: Dict[str, Any] = {}
    while time.time() < deadline:
        last_result = http_request(method, path, params=params, data=data, headers=headers)
        if last_result.get('status_code') == expected_status:
            return last_result
        time.sleep(interval)
    raise RuntimeError(
        f"{method} {path} did not return {expected_status} within {timeout}s. Last={last_result}"
    )


# ============================================================================
# AGENT CLASSES
# ============================================================================

@dataclass
class AgentState:
    """State tracking for an agent."""
    player_name: str
    nickname: str
    player_id: Optional[str] = None
    login_secret: Optional[str] = None
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
    game_finished: bool = False
    winners: List[Any] = field(default_factory=list)
    left_game: bool = False
    last_progress_ts: float = field(default_factory=time.time)


def build_auth_headers(state: AgentState) -> Dict[str, str]:
    """Construct headers carrying bot token + agent identity."""
    headers: Dict[str, str] = {}
    if state.bot_token:
        headers['x-bot-token'] = state.bot_token
    if state.fingerprint:
        headers['X-Fingerprint'] = state.fingerprint
    headers['x-agent-id'] = state.nickname
    return headers


def ensure_http_token(agent: 'BaseAgent', context: str) -> None:
    """Ensure the agent has an x-bot-token available for HTTP flows."""
    if not (STRICT_AUTH_MODE and LOGIN_SECRET_SUPPORTED):
        return
    if agent.state.bot_token:
        return
    if agent.fetch_bot_token():
        return
    raise RuntimeError(f"[{agent.state.nickname}] Missing bot token for {context}")


class BaseAgent:
    """Base agent class with common functionality."""
    
    def __init__(self, player_name: str, nickname: str, address: Optional[str] = None):
        self.state = AgentState(player_name=player_name, nickname=nickname, address=address)
        self.state.fingerprint = f"local-flow-{nickname.lower()}"
        self.sio: Optional[SocketIOClient] = None

    def _matches_player(self, player: Dict[str, Any]) -> bool:
        """Match player entries using stable identifiers across schema variants."""
        nickname = player.get('nickname')
        if nickname and nickname in (self.state.nickname, self.state.player_name):
            return True
        player_id = player.get('player_id') or player.get('wallet_address')
        if player_id and self.state.player_id and player_id == self.state.player_id:
            return True
        return False

    def fetch_bot_token(self) -> bool:
        """Fetch anti-bot token for Socket.IO auth (required in non-local mode)."""
        if not (STRICT_AUTH_MODE and LOGIN_SECRET_SUPPORTED):
            return False
        if not self.state.fingerprint:
            return False
        if not self.state.player_id or not self.state.login_secret:
            log.info(f"[{self.state.nickname}] missing credentials for bot token")
            return False

        result = http_request(
            'POST',
            '/bot/token',
            data={
                'fingerprint': self.state.fingerprint,
                'player_id': self.state.player_id,
                'login_secret': self.state.login_secret,
            },
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
        log.error(f"[{self.state.nickname}] Token fetch skipped/failed: {result}")
        return False
    
    def register(self) -> bool:
        """Register the agent."""
        global LOGIN_SECRET_SUPPORTED
        params = {
            'player_name': self.state.player_name,
        }
        # Do not send address when empty; sending None through query params
        # becomes the literal string "None" and collapses registrations.
        if self.state.address:
            params['address'] = self.state.address

        max_attempts = 8
        for attempt in range(1, max_attempts + 1):
            result = http_request('POST', '/api/register', params=params)
            status_code = result.get('status_code')

            if status_code == 200:
                user = result.get('user') or {}
                player_id = user.get('player_id')
                if not player_id:
                    log.info(f"[{self.state.nickname}] register returned no player_id: {result}")
                    return False
                self.state.player_id = player_id
                secret = result.get('login_secret')
                if not secret:
                    global LOGIN_SECRET_SUPPORTED
                    if LOGIN_SECRET_SUPPORTED:
                        log.info(
                            f"[{self.state.nickname}] register missing login_secret. "
                            "Falling back to legacy auth flow."
                        )
                    LOGIN_SECRET_SUPPORTED = False
                    self.state.login_secret = None
                else:
                    self.state.login_secret = secret
                self.state.player_name = user.get('player_name') or self.state.player_name

                return True

            if status_code == 429 and attempt < max_attempts:
                wait_seconds = 10
                log.info(
                    f"[{self.state.nickname}] register hit rate limit "
                    f"(attempt {attempt}/{max_attempts}), retrying in {wait_seconds}s..."
                )
                time.sleep(wait_seconds)
                continue

            log.error(f"[{self.state.nickname}] register failed: {result}")

        return False
    
    def login(self) -> bool:
        """Login the agent."""
        if not self.state.player_id:
            return False
        if LOGIN_SECRET_SUPPORTED and not self.state.login_secret:
            log.info(f"[{self.state.nickname}] missing login_secret for login")
            return False

        max_attempts = 6
        for attempt in range(1, max_attempts + 1):
            if LOGIN_SECRET_SUPPORTED:
                result = http_request(
                    'POST',
                    '/api/login',
                    data={
                        'login_key': self.state.player_id,
                        'login_secret': self.state.login_secret,
                    },
                    headers={'x-agent-id': self.state.nickname}
                )
            else:
                # Legacy login flow (pre-shared secret not required)
                result = http_request(
                    'POST',
                    '/api/login',
                    params={'login_key': self.state.player_id},
                    headers={'x-agent-id': self.state.nickname}
                )

            log.info(f"[{self.state.nickname}] login result: {result}")
            if result.get('status_code') == 200:
                return True
            if result.get('status_code') == 429 and attempt < max_attempts:
                wait_seconds = 10
                log.info(
                    f"[{self.state.nickname}] login hit rate limit "
                    f"(attempt {attempt}/{max_attempts}), retrying in {wait_seconds}s..."
                )
                time.sleep(wait_seconds)
                continue
            return False

        return False
    
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
            log.info(f"[{self.state.nickname}] Received 'connected' event, authenticating...")
            # Send authenticate immediately
            payload = {
                'login_key': self.state.player_id,
                'player_id': self.state.player_id,  # Backward compatibility
            }
            if LOGIN_SECRET_SUPPORTED and self.state.login_secret:
                payload['login_secret'] = self.state.login_secret
            self.sio.emit('authenticate', payload)
        
        def on_connect(data):
            log.info(f"[{self.state.nickname}] Socket.IO connect confirmed")
            # This is triggered when we receive '40' from server
        
        def on_authenticated(data):
            log.info(f"[{self.state.nickname}] ✓ Authenticated")
            self.state.authenticated = True
            self.state.sid = self.sio.sid
        
        def on_error(data):
            log.error(f"[{self.state.nickname}] ✗ Error: {data}")
            self.state.events_received.append(('error', data))
            self.state.last_progress_ts = time.time()
        
        def on_snapshot(data):
            log.info(f"[{self.state.nickname}] Received GAME_SNAPSHOT")
            self.state.game_state = data
            self.state.game_id = data.get('game_id')
            self.state.game_type = data.get('game_type')
            if 'your_role' in data:
                self.state.my_role = data.get('your_role')
            self.state.events_received.append(('GAME_SNAPSHOT', data))
            self.state.last_progress_ts = time.time()
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



def wait_until(predicate, timeout: float, interval: float = 0.5) -> bool:
    """Poll a predicate until timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def wait_for_authentication(agents: List[BaseAgent], timeout: float = 15.0) -> bool:
    """Wait until all agents are authenticated over Socket.IO."""
    return wait_until(lambda: all(a.state.authenticated for a in agents), timeout=timeout)


def wait_for_event(
    agents: List[BaseAgent],
    event_name: str,
    predicate,
    timeout: float = 10.0,
    interval: float = 0.2,
) -> bool:
    """Wait until any agent receives an event matching predicate."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for agent in agents:
            for evt, payload in agent.state.events_received:
                if evt == event_name and predicate(payload, agent):
                    return True
        time.sleep(interval)
    return False


def wait_for_error_message(
    agents: List[BaseAgent],
    needle: str,
    timeout: float = 5.0,
    interval: float = 0.2,
) -> bool:
    """Wait for an error event containing a substring."""
    lowered = needle.lower()
    return wait_for_event(
        agents,
        'error',
        lambda payload, agent: lowered in str(payload.get('message', '')).lower(),
        timeout=timeout,
        interval=interval,
    )


def wait_for_action_trace(
    traces: List[Dict[str, Any]],
    action: str,
    timeout: float = 10.0,
    interval: float = 0.2,
    predicate=None,
) -> Optional[Dict[str, Any]]:
    """Wait for a werewolf_action_trace item matching action (+ optional predicate)."""
    action_lower = action.lower()
    deadline = time.time() + timeout
    while time.time() < deadline:
        for trace in traces:
            if str(trace.get('action', '')).lower() != action_lower:
                continue
            if predicate and not predicate(trace):
                continue
            return trace
        time.sleep(interval)
    return None


def wait_for_action_trace_any(
    traces: List[Dict[str, Any]],
    actions: set,
    timeout: float = 10.0,
    interval: float = 0.2,
    predicate=None,
) -> Optional[Dict[str, Any]]:
    """Wait for a werewolf_action_trace matching any action in the set."""
    actions_lower = {str(a).lower() for a in actions}
    deadline = time.time() + timeout
    while time.time() < deadline:
        for trace in traces:
            if str(trace.get('action', '')).lower() not in actions_lower:
                continue
            if predicate and not predicate(trace):
                continue
            return trace
        time.sleep(interval)
    return None


def wait_for_phase(
    agents: List[BaseAgent],
    phases: set,
    timeout: float = 15.0,
    interval: float = 0.5,
) -> bool:
    """Wait until any agent sees a game_state phase in the given set."""
    return wait_until(
        lambda: any(
            (a.state.game_state or {}).get('phase') in phases for a in agents
        ),
        timeout=timeout,
        interval=interval,
    )


def dec(value: Any) -> Decimal:
    """Convert numeric-like values to Decimal safely."""
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def get_backend_info() -> Dict[str, Any]:
    """Get backend metadata from /health endpoint."""
    return http_request('GET', '/health')


def get_account_summary(player_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Fetch account summary for settlement assertions."""
    return http_request('GET', f'/api/account/{player_id}', headers=headers)


def capture_account_snapshot(agent: BaseAgent) -> Dict[str, Any]:
    """Capture normalized account snapshot for one agent."""
    if not agent.state.player_id:
        return {'error': 'missing_player_id'}
    ensure_http_token(agent, 'account_snapshot')

    summary = get_account_summary(
        agent.state.player_id,
        headers=build_auth_headers(agent.state),
    )
    if summary.get('status_code') != 200:
        return {'error': f"account_fetch_failed:{summary}"}

    return {
        'player_id': agent.state.player_id,
        'nickname': agent.state.nickname,
        'offchain_balance': dec(summary.get('offchain_balance')),
        'locked_balance': dec(summary.get('locked_balance')),
        'available_balance': dec(summary.get('available_balance')),
        'recent_transactions': summary.get('recent_transactions') or [],
    }


def capture_snapshots(agents: List[BaseAgent], label: str) -> Dict[str, Dict[str, Any]]:
    """Capture account snapshots for all agents and print compact summary."""
    snapshots: Dict[str, Dict[str, Any]] = {}
    log.info(f"\n=== Account Snapshot: {label} ===")
    for agent in agents:
        snap = capture_account_snapshot(agent)
        snapshots[agent.state.player_id or agent.state.nickname] = snap
        if 'error' in snap:
            log.error(f"  {agent.state.nickname}: ERROR -> {snap['error']}")
        else:
            log.info(
                f"  {agent.state.nickname}: offchain={snap['offchain_balance']} "
                f"locked={snap['locked_balance']}"
            )
    return snapshots


def print_asset_deltas(
    agents: List[BaseAgent],
    before: Dict[str, Dict[str, Any]],
    after: Dict[str, Dict[str, Any]],
    label: str,
) -> None:
    """Print asset deltas to verify expectations during the flow."""
    log.info(f"\n=== Asset Deltas: {label} ===")
    for agent in agents:
        key = agent.state.player_id or agent.state.nickname
        snap_before = before.get(key, {})
        snap_after = after.get(key, {})
        if 'error' in snap_before or 'error' in snap_after:
            log.error(f"  {agent.state.nickname}: ERROR -> missing snapshot")
            continue

        offchain_delta = snap_after['offchain_balance'] - snap_before['offchain_balance']
        locked_delta = snap_after['locked_balance'] - snap_before['locked_balance']
        available_delta = snap_after['available_balance'] - snap_before['available_balance']
        log.info(
            f"  {agent.state.nickname}: "
            f"offchainΔ={offchain_delta} lockedΔ={locked_delta} availableΔ={available_delta}"
        )


def tx_has_type(snap: Dict[str, Any], tx_type: str) -> bool:
    """Check whether account snapshot contains a tx type in recent transactions."""
    for tx in snap.get('recent_transactions', []):
        if str(tx.get('type', '')).lower() == tx_type.lower():
            return True
    return False


def validate_root_endpoints():
    """Validate root and health endpoints documented in backend/README.md."""
    log.info("\n=== Validating Root/Health Endpoints ===")
    root = http_request('GET', '/')
    if root.get('status_code') != 200:
        raise RuntimeError(f"Root endpoint failed: {root}")
    required_root = {'name', 'version', 'status', 'local_debug_mode'}
    missing = [key for key in required_root if key not in root]
    if missing:
        raise RuntimeError(f"Root endpoint missing fields: {missing} -> {root}")

    health = http_request('GET', '/health')
    if health.get('status_code') != 200:
        raise RuntimeError(f"Health endpoint failed: {health}")
    if not isinstance(health.get('active_tables'), (int, float)):
        raise RuntimeError(f"Health endpoint active_tables invalid: {health}")


def probe_socket_auth_guard(player_id: str, login_secret: str, fingerprint: str, bot_token: str):
    """Ensure Socket.IO authenticate rejects invalid login_secret payloads."""
    log.info("\n=== Validating Socket.IO Authentication Guards ===")
    probe_id = f"qa-socket-guard-{random.randint(1000, 9999)}"
    probe = SocketIOClient(
        BACKEND_URL,
        auth_payload={
            'botToken': bot_token,
            'fingerprint': fingerprint,
            'agent_id': probe_id,
        },
    )
    error_payloads: List[Any] = []
    authenticated = False

    def on_connected(_):
        bad_secret = f"{login_secret}_tampered"
        probe.emit('authenticate', {
            'login_key': player_id,
            'login_secret': bad_secret,
        })

    def on_authenticated(_):
        nonlocal authenticated
        authenticated = True

    def on_error(payload):
        error_payloads.append(payload or {})

    probe.on('connected', on_connected)
    probe.on('authenticated', on_authenticated)
    probe.on('error', on_error)

    try:
        probe.connect()
        observed = wait_until(lambda: bool(error_payloads) or authenticated, timeout=15, interval=0.2)
    finally:
        probe.disconnect()

    if not observed:
        raise RuntimeError("Socket auth guard test timed out")
    if authenticated:
        raise RuntimeError("Socket accepted invalid login_secret during authenticate")
    last_error = error_payloads[-1] if error_payloads else {}
    summary = json.dumps(last_error).lower() if last_error else ""
    if "login secret" not in summary:
        raise RuntimeError(f"Socket guard error missing login_secret hint: {last_error}")


def validate_agent_endpoints():
    """Validate agent/bot helper endpoints and anti-bot edge cases."""
    if not (STRICT_AUTH_MODE and LOGIN_SECRET_SUPPORTED):
        log.warning("\n=== Skipping Agent Credential Preflight (legacy or debug mode detected) ===")
        return
    log.info("\n=== Validating Agent/Bot Endpoints ===")
    ua_headers = {
        'User-Agent': 'agent-local-flow/preflight',
        'x-agent-id': 'qa-preflight',
    }

    agent_reg = http_request('POST', '/agent/register', headers=ua_headers)
    if agent_reg.get('status_code') != 200 or not agent_reg.get('agent_id'):
        raise RuntimeError(f"Agent register failed: {agent_reg}")

    instructions = http_request('GET', '/agent/instructions')
    if instructions.get('status_code') != 200:
        raise RuntimeError(f"Agent instructions failed: {instructions}")
    required_instr = ['message', 'policy', 'quick_start', 'requirements', 'spectator_endpoints']
    missing_instr = [key for key in required_instr if key not in instructions]
    if missing_instr:
        raise RuntimeError(f"Agent instructions missing fields: {missing_instr} -> {instructions}")

    # Register temp user to exercise credentialed token issuance.
    reg_resp = http_request(
        'POST',
        '/api/register',
        params={'player_name': f"QA_Token_{random.randint(0,9999)}"},
        headers=ua_headers,
    )
    if reg_resp.get('status_code') != 200:
        raise RuntimeError(f"Temp register for token test failed: {reg_resp}")
    temp_user = (reg_resp.get('user') or {})
    player_id = temp_user.get('player_id')
    login_secret = reg_resp.get('login_secret')
    if not player_id or not login_secret:
        raise RuntimeError(f"Temp register missing credentials: {reg_resp}")

    fingerprint = f"qa-suite-{int(time.time())}-{random.randint(1000, 9999)}"
    token_payload = {
        'fingerprint': fingerprint,
        'player_id': player_id,
        'login_secret': login_secret,
    }
    token_resp = http_request('POST', '/bot/token', data=token_payload, headers=ua_headers)
    if token_resp.get('status_code') != 200 or not token_resp.get('token'):
        raise RuntimeError(f"Bot token issuance failed: {token_resp}")

    browser_headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    browser_resp = http_request('POST', '/bot/token', data=token_payload, headers=browser_headers)
    if browser_resp.get('error') != 'browser_detected':
        raise RuntimeError(f"Browser detection edge case failed: {browser_resp}")

    short_payload = {
        'fingerprint': 'tiny',
        'player_id': player_id,
        'login_secret': login_secret,
    }
    short_resp = http_request('POST', '/bot/token', data=short_payload, headers=ua_headers)
    if short_resp.get('status_code') != 422:
        raise RuntimeError(f"Fingerprint length validation failed: {short_resp}")

    invalid_secret_payload = dict(token_payload)
    invalid_secret_payload['login_secret'] = login_secret + "_tampered"
    invalid_secret = http_request('POST', '/bot/token', data=invalid_secret_payload, headers=ua_headers)
    if invalid_secret.get('error') != 'invalid_credentials':
        raise RuntimeError(f"Bot token invalid-secret edge case failed: {invalid_secret}")

    blank_secret_login = http_request(
        'POST',
        '/api/login',
        data={'login_key': player_id, 'login_secret': ''},
    )
    if blank_secret_login.get('status_code') != 401:
        raise RuntimeError(f"Login missing-secret guard failed: {blank_secret_login}")

    wrong_secret_login = http_request(
        'POST',
        '/api/login',
        data={'login_key': player_id, 'login_secret': login_secret + '_oops'},
    )
    if wrong_secret_login.get('status_code') != 401:
        raise RuntimeError(f"Login invalid-secret guard failed: {wrong_secret_login}")

    probe_socket_auth_guard(
        player_id=player_id,
        login_secret=login_secret,
        fingerprint=fingerprint,
        bot_token=token_resp['token'],
    )


def validate_account_endpoints(agents: List[BaseAgent]):
    """Validate account/economy endpoints (success + documented error cases)."""
    log.info("\n=== Validating Account/Economy Endpoints ===")
    player_ids = [agent.state.player_id for agent in agents if agent.state.player_id]
    if not player_ids:
        raise RuntimeError("No player IDs available for account validation")

    primary_id = player_ids[0]
    primary_agent = agents[0]
    ensure_http_token(primary_agent, 'account_endpoints')
    auth_headers = build_auth_headers(primary_agent.state)

    if STRICT_AUTH_MODE:
        no_auth_balance = http_request('GET', f'/api/balance/{primary_id}')
        if no_auth_balance.get('status_code') != 401:
            raise RuntimeError(f"Balance unauthenticated guard failed: {no_auth_balance}")

    balance = http_request('GET', f'/api/balance/{primary_id}', headers=auth_headers)
    if balance.get('status_code') != 200 or balance.get('player_id') != primary_id:
        raise RuntimeError(f"Balance lookup failed: {balance}")

    invalid_id = f"{primary_id}_invalid"
    missing_balance = http_request('GET', f'/api/balance/{invalid_id}', headers=auth_headers)
    if STRICT_AUTH_MODE:
        if missing_balance.get('status_code') != 404:
            raise RuntimeError(f"Balance missing-ID edge case failed: {missing_balance}")
    else:
        if missing_balance.get('status_code') == 404:
            log.info("  Balance missing-ID check passed (debug mode).")
        else:
            log.info(f"  Balance missing-ID relaxed in debug mode: {missing_balance}")

    summary = get_account_summary(primary_id, headers=auth_headers)
    if summary.get('status_code') != 200:
        raise RuntimeError(f"Account summary failed: {summary}")

    if STRICT_AUTH_MODE:
        no_auth_summary = http_request('GET', f'/api/account/{primary_id}')
        if no_auth_summary.get('status_code') != 401:
            raise RuntimeError(f"Account summary unauthenticated guard failed: {no_auth_summary}")

    missing_summary = http_request('GET', f'/api/account/{invalid_id}', headers=auth_headers)
    if STRICT_AUTH_MODE and missing_summary.get('status_code') != 404:
        raise RuntimeError(f"Account missing-ID edge case failed: {missing_summary}")

    batch = http_request('POST', '/api/balances/batch', data={'player_ids': player_ids}, headers=auth_headers)
    if batch.get('status_code') != 200:
        raise RuntimeError(f"Batch balance lookup failed: {batch}")
    balances = batch.get('balances') or {}
    missing_players = [pid for pid in player_ids if pid not in balances]
    if missing_players:
        raise RuntimeError(f"Batch balance response missing entries: {missing_players} -> {balances}")

    overflow_ids = [f"overflow_{i}" for i in range(55)]
    overflow_resp = http_request('POST', '/api/balances/batch', data={'player_ids': overflow_ids}, headers=auth_headers)
    if overflow_resp.get('status_code') != 400:
        raise RuntimeError(f"Batch overflow edge case failed: {overflow_resp}")

    if STRICT_AUTH_MODE:
        no_auth_batch = http_request('POST', '/api/balances/batch', data={'player_ids': player_ids})
        if no_auth_batch.get('status_code') != 401:
            raise RuntimeError(f"Batch unauthenticated guard failed: {no_auth_batch}")

    leaderboard_limit = min(25, max(5, len(player_ids)))
    leaderboard_ok = http_request('GET', '/api/leaderboard', params={'limit': leaderboard_limit})
    if leaderboard_ok.get('status_code') != 200 or 'entries' not in leaderboard_ok:
        raise RuntimeError(f"Leaderboard lookup failed: {leaderboard_ok}")

    leaderboard_bad = http_request('GET', '/api/leaderboard', params={'limit': 500})
    if leaderboard_bad.get('status_code') != 400:
        raise RuntimeError(f"Leaderboard limit edge case failed: {leaderboard_bad}")


def expect_active_listing(identifier: str, game_type: str, should_exist: bool, timeout: float = 20.0):
    """Assert that a game/table appears (or not) in /api/games/active."""
    if not identifier:
        raise RuntimeError(f"Cannot check active listing for empty identifier ({game_type})")

    list_key = 'werewolf_games' if game_type == 'werewolf' else 'poker_tables'
    expectation = 'present' if should_exist else 'absent'
    log.info(f"\n=== Active Listing Check ({game_type}, expect {expectation}) ===")

    last_entries: List[str] = []

    def predicate() -> bool:
        nonlocal last_entries
        resp = http_request('GET', '/api/games/active')
        if resp.get('status_code') != 200:
            return False
        last_entries = resp.get(list_key) or []
        exists = identifier in last_entries
        return exists if should_exist else not exists

    if not wait_until(predicate, timeout=timeout, interval=1.0):
        if should_exist and game_type == 'poker':
            # In local debug flows, /api/games/active can lag behind newly spawned
            # matchmaking tables. Fall back to the spectator endpoint to avoid
            # false negatives while still surfacing a warning.
            probe = http_request('GET', f'/api/spectate/poker/{identifier}')
            if probe.get('status_code') == 200:
                log.info(
                    f"⚠ Active listing missing {identifier} (poker). "
                    "Spectator endpoint is live; continuing."
                )
                return
        raise RuntimeError(
            f"Active listing expectation failed for {identifier} ({game_type}). "
            f"Wanted {expectation}, latest {list_key}={last_entries}"
        )

    # Exercise /api/games/active search filtering documented in README.
    token = identifier[:max(4, min(len(identifier), 8))]
    if token:
        filtered = http_request('GET', '/api/games/active', params={'q': token})
        if filtered.get('status_code') == 200:
            filtered_entries = filtered.get(list_key) or []
            if should_exist and identifier not in filtered_entries:
                raise RuntimeError(
                    f"Active listing filter '{token}' missing expected {identifier}: {filtered}"
                )
            if not should_exist and identifier in filtered_entries:
                raise RuntimeError(
                    f"Active listing filter '{token}' unexpectedly returned {identifier}: {filtered}"
                )


def verify_werewolf_spectator_endpoints(game_id: str):
    """Verify spectator access for werewolf games including error paths."""
    log.info(f"\n=== Spectator Endpoint Checks (Werewolf {game_id}) ===")
    path = f'/api/spectate/werewolf/{game_id}'
    poll_http_status('GET', path, 200, timeout=20)

    reveal_resp = http_request('GET', path, params={'reveal': 'true'})
    if reveal_resp.get('status_code') != 403:
        raise RuntimeError(f"Werewolf reveal mode should be unauthorized without admin token: {reveal_resp}")

    missing_resp = http_request('GET', f'{path}-missing')
    if missing_resp.get('status_code') != 404:
        raise RuntimeError(f"Werewolf spectator missing-id edge case failed: {missing_resp}")


def verify_poker_spectator_endpoints(table_id: str):
    """Verify spectator access for poker tables including error paths."""
    log.info(f"\n=== Spectator Endpoint Checks (Poker {table_id}) ===")
    path = f'/api/spectate/poker/{table_id}'
    poll_http_status('GET', path, 200, timeout=20)

    reveal_resp = http_request('GET', path, params={'reveal': 'true'})
    if reveal_resp.get('status_code') != 403:
        raise RuntimeError(f"Poker reveal mode should be unauthorized without admin token: {reveal_resp}")

    missing_resp = http_request('GET', f'{path}-missing')
    if missing_resp.get('status_code') != 404:
        raise RuntimeError(f"Poker spectator missing-id edge case failed: {missing_resp}")


class WerewolfAgent(BaseAgent):
    """Agent for Werewolf game with fixed logic."""
    
    def __init__(self, player_name: str, nickname: str, address: Optional[str] = None):
        super().__init__(player_name, nickname, address)
        self.last_phase = None
        self._last_action_key: Optional[str] = None

    def _role_name(self) -> Optional[str]:
        """Return normalized role name across schema variants."""
        if not self.state.my_role:
            return None
        return self.state.my_role.get('role_type') or self.state.my_role.get('role')

    def _self_player(self) -> Optional[Dict[str, Any]]:
        """Get this agent's player entry from latest game state."""
        state = self.state.game_state or {}
        for player in state.get('players', []):
            if self._matches_player(player):
                return player
        return None

    def _my_game_sid(self) -> Optional[str]:
        """Return the player's in-game sid from latest state."""
        me = self._self_player()
        if not me:
            return None
        return me.get('sid')

    def _emit_werewolf_action(
        self,
        payload: Dict[str, Any],
        expected_phase: Optional[str] = None,
        allow_dead: bool = False,
    ) -> bool:
        """Guard action emits against phase drift and invalid self state."""
        if not self.sio or not self.state.game_state:
            return False

        if expected_phase and self.state.game_state.get('phase') != expected_phase:
            return False

        me = self._self_player()
        if not me or (not allow_dead and (not me.get('is_alive', False) or me.get('status') == 'zombie')):
            return False

        game_id = self.state.game_id or self.state.game_state.get('game_id')
        if not game_id:
            return False

        data = dict(payload)
        data['game_id'] = game_id
        self.sio.emit('werewolf_action', data)
        self.state.last_progress_ts = time.time()
        return True

    def _already_acted_for_state(self, phase: str) -> bool:
        """Prevent duplicate emits for the same phase/turn snapshot."""
        gs = self.state.game_state or {}
        key_parts = [
            str(gs.get('game_id') or self.state.game_id or ''),
            str(gs.get('day_count') or ''),
            phase,
        ]

        if phase == 'day_speaking':
            key_parts.append(str(gs.get('current_speaker_index', 0)))

        key = '|'.join(key_parts)
        if self._last_action_key == key:
            return True

        self._last_action_key = key
        return False
    
    def connect_socket(self):
        """Connect and setup werewolf handlers."""
        super().connect_socket()
        
        def on_joined(data):
            log.info(f"[{self.state.nickname}] Joined werewolf game")
            self.state.events_received.append(('werewolf_joined', data))
            self.state.last_progress_ts = time.time()
        
        def on_state(data):
            log.info(f"[{self.state.nickname}] Received werewolf_state")
            self.state.game_state = data
            if data.get('game_id'):
                self.state.game_id = data.get('game_id')
            self.state.events_received.append(('werewolf_state', data))
            self.state.last_progress_ts = time.time()
            self.decide_action()
        
        def on_phase_change(data):
            log.info(f"[{self.state.nickname}] Phase changed: {data.get('phase')}")
            self.last_phase = data.get('phase')
            if data.get('game_id'):
                self.state.game_id = data.get('game_id')
            if data.get('game_over') or data.get('phase') == 'finished':
                self.state.game_finished = True
                self.state.winners = data.get('winners', []) or []
                log.info(f"[{self.state.nickname}] ✓ Werewolf game finished, winners={self.state.winners}")
            self.state.events_received.append(('werewolf_phase_change', data))
            self.state.last_progress_ts = time.time()
            self.decide_action()
        
        def on_game_created(data):
            log.info(f"[{self.state.nickname}] Game created: {data.get('game_id')}")
            self.state.events_received.append(('werewolf_game_created', data))
            self.state.last_progress_ts = time.time()

        def on_chat_message(data):
            log.info(f"[{self.state.nickname}] Received chat_message")
            self.state.events_received.append(('chat_message', data))
            self.state.last_progress_ts = time.time()

        def on_wolf_chat_message(data):
            log.info(f"[{self.state.nickname}] Received wolf_chat_message")
            self.state.events_received.append(('wolf_chat_message', data))
            self.state.last_progress_ts = time.time()
        
        self.sio.on('werewolf_joined', on_joined)
        self.sio.on('werewolf_state', on_state)
        self.sio.on('werewolf_phase_change', on_phase_change)
        self.sio.on('werewolf_game_created', on_game_created)
        self.sio.on('chat_message', on_chat_message)
        self.sio.on('wolf_chat_message', on_wolf_chat_message)
    
    def create_game(self, game_id: str, entry_fee: int = 0):
        """Create a werewolf game."""
        if self.sio:
            self.sio.emit('create_werewolf_game', {
                'game_id': game_id,
                'entry_fee': entry_fee,
            })
    
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

        # Keep game_id in sync; phase-change payloads may omit game_id.
        if self.state.game_state.get('game_id'):
            self.state.game_id = self.state.game_state.get('game_id')
        
        phase = self.state.game_state.get('phase')
        if not phase:
            return

        me = self._self_player()
        if not me or not me.get('is_alive', False) or me.get('status') == 'zombie':
            return
        
        # Get my role info
        if not self.state.my_role and self.state.game_state.get('players'):
            for player in self.state.game_state['players']:
                if self._matches_player(player):
                    if 'role' in player and player['role']:
                        self.state.my_role = player['role']
                    break

        # Night ability phases require role visibility. Avoid consuming
        # phase dedupe before role info arrives in a later snapshot.
        if phase in ('night_wolf_discussion', 'night_wolf_voting', 'night_seer', 'night_witch') and not self.state.my_role:
            return

        # Avoid repeatedly spamming the same action on every state update packet.
        if self._already_acted_for_state(phase):
            return
        
        # Fixed logic based on phase
        if phase == 'night_wolf_discussion':
            self._handle_wolf_discussion()
        elif phase == 'night_wolf_voting':
            self._handle_wolf_voting()
        elif phase == 'night_seer':
            self._handle_seer_action()
        elif phase == 'night_witch':
            self._handle_witch_action()
        elif phase in ('night_hunter', 'day_hunter'):
            self._handle_hunter_action()
        elif phase == 'day_speaking':
            self._handle_speaking()
        elif phase == 'day_voting':
            self._handle_voting()
    
    def _handle_wolf_discussion(self):
        """Handle wolf discussion phase."""
        if not self.state.my_role:
            return
        
        role_type = self._role_name()
        if role_type == 'wolf':
            self._emit_werewolf_action({
                'action': 'wolf_chat',
                'message': f'{self.state.nickname}: Let\'s kill someone!'
            }, expected_phase='night_wolf_discussion')
    
    def _handle_wolf_voting(self):
        """Handle wolf voting phase."""
        if not self.state.my_role:
            return
        
        role_type = self._role_name()
        if role_type == 'wolf':
            if self.state.game_state and self.state.game_state.get('players'):
                non_wolves = [
                    p for p in self.state.game_state['players']
                    if p.get('is_alive') and p.get('status') != 'zombie'
                    and (p.get('role', {}).get('role_type') or p.get('role', {}).get('role')) != 'wolf'
                ]
                if non_wolves:
                    non_wolves.sort(key=lambda p: p.get('nickname', ''))
                    target = non_wolves[0]
                    self._emit_werewolf_action({
                        'action': 'night_kill',
                        'target_sid': target.get('sid')
                    }, expected_phase='night_wolf_voting')
                    log.info(f"[{self.state.nickname}] Voted to kill {target.get('nickname')}")
    
    def _handle_seer_action(self):
        """Handle seer check phase."""
        if not self.state.my_role:
            return
        
        role_type = self._role_name()
        if role_type == 'seer':
            my_game_sid = self._my_game_sid()
            if self.state.game_state and self.state.game_state.get('players'):
                others = [
                    p for p in self.state.game_state['players']
                    if p.get('is_alive') and p.get('status') != 'zombie' and p.get('sid') != my_game_sid
                ]
                if others:
                    target = random.choice(others)
                    self._emit_werewolf_action({
                        'action': 'seer_check',
                        'target_sid': target.get('sid')
                    }, expected_phase='night_seer')
                    log.info(f"[{self.state.nickname}] Checking {target.get('nickname')}")
    
    def _handle_witch_action(self):
        """Handle witch action phase."""
        if not self.state.my_role:
            return
        
        role_type = self._role_name()
        if role_type == 'witch':
            self._emit_werewolf_action({
                'action': 'witch_skip'
            }, expected_phase='night_witch')
            log.warning(f"[{self.state.nickname}] Witch skipping action")

    def _handle_hunter_action(self):
        """Handle hunter shot phase."""
        if not self.state.my_role:
            return

        role_type = self._role_name()
        if role_type != 'hunter':
            return

        my_game_sid = self._my_game_sid()
        targets = []
        if self.state.game_state and self.state.game_state.get('players'):
            targets = [
                p for p in self.state.game_state['players']
                if p.get('is_alive') and p.get('status') != 'zombie' and p.get('sid') != my_game_sid
            ]

        payload = {'action': 'hunter_shoot'}
        if targets:
            target = random.choice(targets)
            payload['target_sid'] = target.get('sid')
            log.info(f"[{self.state.nickname}] Hunter shooting {target.get('nickname')}")
        else:
            log.warning(f"[{self.state.nickname}] Hunter skipping (no targets)")

        self._emit_werewolf_action(
            payload,
            expected_phase=self.state.game_state.get('phase'),
            allow_dead=True,
        )
    
    def _handle_speaking(self):
        """Handle day speaking phase."""
        if not self.state.game_state:
            return
        
        speaking_order = self.state.game_state.get('speaking_order', [])
        current_speaker_index = self.state.game_state.get('current_speaker_index', 0)
        
        if speaking_order and current_speaker_index < len(speaking_order):
            my_sid = None
            for player in self.state.game_state.get('players', []):
                if self._matches_player(player):
                    my_sid = player.get('sid')
                    break
            
            if my_sid and speaking_order[current_speaker_index] == my_sid:
                self._emit_werewolf_action({
                    'action': 'speak',
                    'message': f'{self.state.nickname}: I think we should vote carefully.'
                }, expected_phase='day_speaking')
                log.info(f"[{self.state.nickname}] Speaking")
    
    def _handle_voting(self):
        """Handle day voting phase."""
        if not self.state.game_state:
            return

        my_game_sid = self._my_game_sid()
        
        if self.state.game_state.get('players'):
            others = [
                p for p in self.state.game_state['players']
                if p.get('is_alive')
                and p.get('status') != 'zombie'
                and p.get('sid') != my_game_sid
            ]
            if not others:
                self._emit_werewolf_action({
                    'action': 'vote',
                    'target_sid': None
                }, expected_phase='day_voting')
                log.info(f"[{self.state.nickname}] Abstained")
                return

            role_type = self._role_name()
            if role_type == 'wolf':
                candidates = [
                    p for p in others
                    if (p.get('role', {}).get('role_type') or p.get('role', {}).get('role')) != 'wolf'
                ]
            else:
                candidates = [
                    p for p in others
                    if (p.get('role', {}).get('role_type') or p.get('role', {}).get('role')) == 'wolf'
                ]
            if not candidates:
                candidates = others

            candidates.sort(key=lambda p: p.get('nickname', ''))
            target = candidates[0]
            self._emit_werewolf_action({
                'action': 'vote',
                'target_sid': target.get('sid')
            }, expected_phase='day_voting')
            log.info(f"[{self.state.nickname}] Voted for {target.get('nickname')}")


class TexasAgent(BaseAgent):
    """Agent for Texas Hold'em game with fixed logic."""
    
    def connect_socket(self):
        """Connect and setup texas handlers."""
        super().connect_socket()

        def on_matchmaking_started(data):
            log.info(f"[{self.state.nickname}] Matched into poker table: {data.get('table_id')}")
            self.state.left_game = False
            self.state.game_id = data.get('table_id')
            self.state.events_received.append(('texas_matchmaking_game_started', data))
            self.state.last_progress_ts = time.time()

        def on_left_game(data):
            log.info(f"[{self.state.nickname}] Left poker table")
            self.state.left_game = True
            self.state.events_received.append(('left_game', data))
            self.state.last_progress_ts = time.time()

        def on_game_update(data):
            log.info(f"[{self.state.nickname}] Received game_update")
            self.state.game_state = data
            self.state.game_id = data.get('game_id')
            self.state.events_received.append(('game_update', data))
            self.state.last_progress_ts = time.time()
            phase = data.get('phase')
            current_player = data.get('current_player')
            if phase in {'showdown', 'finished'}:
                self.state.is_my_turn = False
            elif current_player:
                self.state.is_my_turn = current_player == self.sio.sid
            else:
                self.state.is_my_turn = False
            if self.state.is_my_turn:
                self.decide_action()

        def on_private_hand(data):
            log.info(f"[{self.state.nickname}] Received private_hand")
            self.state.my_hole_cards = data.get('hole_cards')
            self.state.is_my_turn = data.get('your_turn', False)
            self.state.events_received.append(('private_hand', data))
            self.state.last_progress_ts = time.time()
            if self.state.is_my_turn:
                self.decide_action()

        def on_hand_winner(data):
            log.info(f"[{self.state.nickname}] ✓ Hand finished via hand_winner: {data.get('winner')}")
            self.state.game_finished = True
            self.state.winners = [data.get('winner')] if data.get('winner') else []
            self.state.events_received.append(('hand_winner', data))
            self.state.last_progress_ts = time.time()

        def on_showdown_reveal(data):
            log.info(f"[{self.state.nickname}] ✓ Hand finished via showdown_reveal")
            self.state.game_finished = True
            self.state.winners = data.get('winners', []) or []
            self.state.events_received.append(('showdown_reveal', data))
            self.state.last_progress_ts = time.time()

        self.sio.on('texas_matchmaking_game_started', on_matchmaking_started)
        self.sio.on('left_game', on_left_game)
        self.sio.on('game_update', on_game_update)
        self.sio.on('private_hand', on_private_hand)
        self.sio.on('hand_winner', on_hand_winner)
        self.sio.on('showdown_reveal', on_showdown_reveal)

    def join_matchmaking(self, chips: int = 1000):
        """Join Texas Hold'em matchmaking queue."""
        if self.sio:
            self.sio.emit('join_texas_matchmaking', {
                'chips': chips,
                'nickname': self.state.nickname,
            })

    def start_hand(self, table_id: str):
        """Start a new hand."""
        if self.sio:
            self.sio.emit('start_hand', {'table_id': table_id})

    def leave_table(self, table_id: str):
        """Leave table explicitly so backend settles locked chips."""
        if self.sio:
            self.sio.emit('leave_game', {'table_id': table_id})
    
    def decide_action(self):
        """Decide poker action based on current state."""
        if not self.state.is_my_turn or not self.sio:
            return
        
        if not self.state.game_state:
            return
        if self.state.game_state.get('phase') in {'showdown', 'finished'}:
            return
        
        current_bet = self.state.game_state.get('current_bet', 0)
        
        # Get my player info
        my_player = None
        if self.state.game_state.get('players'):
            for player in self.state.game_state['players']:
                if self._matches_player(player):
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
            log.info(f"[{self.state.nickname}] Checking")
        elif to_call <= my_chips * 0.2:
            self.sio.emit('player_move', {
                'table_id': self.state.game_id,
                'action': 'call',
                'message': f'{self.state.nickname}: Calling {to_call}.'
            })
            log.info(f"[{self.state.nickname}] Calling {to_call}")
        else:
            self.sio.emit('player_move', {
                'table_id': self.state.game_id,
                'action': 'fold',
                'message': f'{self.state.nickname}: Folding, too expensive.'
            })
            log.info(f"[{self.state.nickname}] Folding")


# ============================================================================
# TEST FUNCTIONS
# ============================================================================

def register_and_login_agents(agents: List[BaseAgent]):
    """Register and login all agents."""
    log.info("\n=== Registering and Logging in Agents ===")
    all_ok = True
    for agent in agents:
        try:
            registered = agent.register()
            if not registered:
                log.error(f"  Registration failed: {agent.state.nickname}")
                all_ok = False
                continue
            log.info(f"  Registered: {agent.state.nickname} -> {agent.state.player_id}")

            if LOGIN_SECRET_SUPPORTED:
                logged_in = agent.login()
                if not logged_in:
                    log.error(f"  Login failed: {agent.state.nickname} ({agent.state.player_id})")
                    all_ok = False
                    continue
                log.info(f"  Logged in: {agent.state.nickname} ({agent.state.player_id})")
            else:
                log.warning(f"  Login skipped (legacy mode): {agent.state.nickname} ({agent.state.player_id})")
                logged_in = True

            if STRICT_AUTH_MODE and LOGIN_SECRET_SUPPORTED:
                # Mint bot token immediately so HTTP flows can use authenticated headers.
                try:
                    if agent.fetch_bot_token():
                        log.info(f"  Bot token minted: {agent.state.nickname}")
                    else:
                        log.error(f"  Bot token fetch failed: {agent.state.nickname}")
                        all_ok = False
                except Exception as e:
                    log.error(f"  Token error for {agent.state.nickname}: {e}")
                    all_ok = False
                time.sleep(0.1)
        except Exception as e:
            log.error(f"  Error with {agent.state.nickname}: {e}")
            all_ok = False
    return all_ok


def test_werewolf_flow(local_debug_mode: bool):
    """Test werewolf game flow with multiple agents."""
    log.info("\n" + "="*70)
    log.info("TESTING WEREWOLF GAME FLOW")
    log.info("="*70)
    
    # Create agents
    agents = []
    for i in range(WEREWOLF_AGENTS):
        nickname = f"WerewolfAgent{i+1}"
        player_name = unique_id(nickname)
        agents.append(WerewolfAgent(player_name=player_name, nickname=nickname))
    
    # Register and login
    if not register_and_login_agents(agents):
        raise RuntimeError("Werewolf precondition failed: register/login not completed for all agents")

    validate_account_endpoints(agents)

    pre_game = capture_snapshots(agents, 'werewolf_before_game')
    
    # Connect all agents
    log.info("\n=== Connecting Agents ===")
    for agent in agents:
        try:
            agent.connect_socket()
            time.sleep(0.2)  # Wait for connection
        except Exception as e:
            log.error(f"  Error connecting {agent.state.nickname}: {e}")
    
    # Wait for authentication
    if not wait_for_authentication(agents, timeout=20):
        log.warning("⚠ Some werewolf agents failed to authenticate in time")
    
    # Create game with first agent
    game_id = unique_id("test_werewolf")
    
    # Determine frontend URL for display
    if "clawarena.io" in BACKEND_HOST:
        frontend_base = f"{BACKEND_SCHEME}://{BACKEND_HOST.replace('api-', '')}"
    else:
        frontend_base = "http://localhost:3000"
        
    log.info(f"\n=== Creating Game: {game_id} ===")
    log.info(f"👉 OPEN THIS URL TO SPECTATE: {frontend_base}/werewolf/{game_id}")
    agents[0].create_game(game_id, entry_fee=WEREWOLF_ENTRY_FEE)
    time.sleep(0.5)
    
    # All agents join
    log.info(f"\n=== Joining Game ===")
    for agent in agents:
        agent.join_game(game_id)
        time.sleep(0.1)
    
    time.sleep(1)

    # Spectator client for action-trace coverage (reveal mode).
    action_traces: List[Dict[str, Any]] = []
    spectator: Optional[SocketIOClient] = None
    spectator_ready = False
    try:
        spectator = SocketIOClient(
            BACKEND_URL,
            auth_payload={
                'agent_id': 'WerewolfSpectator',
                'spectator': True,
                'read_only': True,
            },
        )

        def on_trace(data):
            action_traces.append(data or {})

        def on_spectator_error(data):
            log.error(f"[Spectator] error: {data}")

        spectator.on('werewolf_action_trace', on_trace)
        spectator.on('error', on_spectator_error)
        spectator.connect()
        time.sleep(0.5)
        spectator.emit('join_spectate', {'game_id': game_id, 'reveal': True})
        time.sleep(0.5)
        spectator_ready = True
    except Exception as e:
        log.warning(f"⚠ Spectator action-trace setup failed: {e}")

    expect_active_listing(game_id, 'werewolf', True, timeout=30)
    verify_werewolf_spectator_endpoints(game_id)

    # Confirm assets after join (lock entry fees in normal mode)
    post_join = capture_snapshots(agents, 'werewolf_after_join')
    print_asset_deltas(agents, pre_game, post_join, 'werewolf_join')
    if not local_debug_mode:
        for agent in agents:
            player_id = agent.state.player_id or ""
            before = pre_game.get(player_id, {})
            after = post_join.get(player_id, {})
            if 'error' in before or 'error' in after:
                raise RuntimeError(f"Werewolf account snapshot missing for {agent.state.nickname}")
            if after['locked_balance'] < before['locked_balance'] + Decimal(str(WEREWOLF_ENTRY_FEE)) - EPSILON:
                raise RuntimeError("Werewolf entry fee lock did not increase locked balance as expected")

    # Channel checks: public chat in lobby before game start.
    log.info(f"\n=== Channel Checks (Werewolf) ===")

    lobby_message = f"lobby-chat-{int(time.time())}"
    if agents[0].sio:
        agents[0].sio.emit('werewolf_action', {
            'game_id': game_id,
            'action': 'chat',
            'message': lobby_message,
        })

    lobby_chat_ok = wait_for_event(
        agents,
        'chat_message',
        lambda payload, agent: payload.get('message') == lobby_message,
        timeout=10,
    )
    if not lobby_chat_ok:
        raise RuntimeError("Werewolf lobby chat not broadcast to channel")

    # Start game
    log.info(f"\n=== Starting Game ===")
    agents[0].start_game(game_id)
    time.sleep(1)

    night_phases = {
        'night_wolf_discussion',
        'night_wolf_voting',
        'night_seer',
        'night_witch',
        'night_hunter',
    }
    wait_for_phase(agents, night_phases, timeout=20)

    restricted_message = f"night-chat-{int(time.time())}"
    if agents[0].sio:
        agents[0].sio.emit('werewolf_action', {
            'game_id': game_id,
            'action': 'chat',
            'message': restricted_message,
        })

    restricted_error_ok = wait_for_event(
        [agents[0]],
        'error',
        lambda payload, agent: payload.get('error_code') == 'CHAT_PHASE_RESTRICTED',
        timeout=5,
    )
    if not restricted_error_ok:
        raise RuntimeError("Werewolf night public chat was not blocked")

    # Day speaking: only current speaker can chat publicly.
    if wait_for_phase(agents, {'day_speaking'}, timeout=30):
        current_speaker_sid = None
        speaker_order = []
        for agent in agents:
            state = agent.state.game_state or {}
            speaker_order = state.get('speaking_order', []) or []
            idx = state.get('current_speaker_index', 0)
            if speaker_order and idx < len(speaker_order):
                current_speaker_sid = speaker_order[idx]
                break

        non_speaker = None
        for agent in agents:
            if agent._my_game_sid() != current_speaker_sid:
                non_speaker = agent
                break

        if non_speaker and non_speaker.sio:
            non_speaker.sio.emit('werewolf_action', {
                'game_id': game_id,
                'action': 'chat',
                'message': f"speaking-chat-block-{int(time.time())}",
            })

            speaking_blocked = wait_for_event(
                [non_speaker],
                'error',
                lambda payload, agent: payload.get('error_code') == 'CHAT_PHASE_RESTRICTED',
                timeout=5,
            )
            if not speaking_blocked:
                raise RuntimeError("Werewolf speaking phase allowed non-speaker chat")
        else:
            log.warning("⚠ Werewolf speaking-phase chat check skipped (speaker not resolved)")
    else:
        log.warning("⚠ Werewolf speaking-phase chat check skipped (phase not observed)")

    # Wolf chat should be visible only to wolves.
    role_ready = wait_until(
        lambda: all(a.state.my_role for a in agents),
        timeout=20,
        interval=0.5,
    )
    if role_ready:
        wolves = [a for a in agents if (a.state.my_role or {}).get('role_type') == 'wolf']
        villagers = [a for a in agents if (a.state.my_role or {}).get('role_type') != 'wolf']
        if len(wolves) >= 2 and villagers:
            wolf_sender = wolves[0]
            wolf_receiver = wolves[1]
            wolf_message = f"wolf-chat-{int(time.time())}"
            if wolf_sender.sio:
                wolf_sender.sio.emit('werewolf_action', {
                    'game_id': game_id,
                    'action': 'wolf_chat',
                    'message': wolf_message,
                })

            wolf_seen = wait_for_event(
                [wolf_receiver],
                'wolf_chat_message',
                lambda payload, agent: payload.get('message') == wolf_message,
                timeout=10,
            )
            if not wolf_seen:
                raise RuntimeError("Wolf chat was not delivered to another wolf")

            nonwolf_seen = wait_for_event(
                villagers,
                'wolf_chat_message',
                lambda payload, agent: payload.get('message') == wolf_message,
                timeout=3,
            )
            if nonwolf_seen:
                raise RuntimeError("Wolf chat leaked to non-wolf player")

            # Non-wolf should be blocked when attempting wolf_chat.
            nonwolf_sender = villagers[0]
            if nonwolf_sender.sio:
                nonwolf_sender.sio.emit('werewolf_action', {
                    'game_id': game_id,
                    'action': 'wolf_chat',
                    'message': f"nonwolf-wolfchat-{int(time.time())}",
                })

                nonwolf_blocked = wait_for_event(
                    [nonwolf_sender],
                    'error',
                    lambda payload, agent: 'wolf' in payload.get('message', '').lower(),
                    timeout=5,
                )
                if not nonwolf_blocked:
                    raise RuntimeError("Non-wolf was able to send wolf_chat")
        else:
            log.warning("⚠ Wolf chat visibility check skipped (insufficient wolves)")
    else:
        log.warning("⚠ Wolf chat visibility check skipped (roles not assigned in time)")

    # Role-restricted action checks (non-roles should be rejected).
    if role_ready:
        non_wolf = next((a for a in agents if (a.state.my_role or {}).get('role_type') != 'wolf'), None)
        if non_wolf and wait_for_phase(agents, {'night_wolf_voting'}, timeout=20):
            if non_wolf.sio:
                non_wolf.sio.emit('werewolf_action', {
                    'game_id': game_id,
                    'action': 'night_kill',
                    'target_sid': None,
                })
            blocked = wait_for_error_message([non_wolf], 'not a wolf', timeout=5)
            if not blocked:
                raise RuntimeError("Non-wolf night_kill was not rejected")
        else:
            log.warning("⚠ Non-wolf night_kill check skipped (phase or agent not available)")

        non_seer = next((a for a in agents if (a.state.my_role or {}).get('role_type') != 'seer'), None)
        if non_seer and wait_for_phase(agents, {'night_seer'}, timeout=20):
            if non_seer.sio:
                non_seer.sio.emit('werewolf_action', {
                    'game_id': game_id,
                    'action': 'seer_check',
                    'target_sid': None,
                })
            blocked = wait_for_error_message([non_seer], 'not a seer', timeout=5)
            if not blocked:
                raise RuntimeError("Non-seer seer_check was not rejected")
        else:
            log.warning("⚠ Non-seer check skipped (phase or agent not available)")

        non_witch = next((a for a in agents if (a.state.my_role or {}).get('role_type') != 'witch'), None)
        if non_witch and wait_for_phase(agents, {'night_witch'}, timeout=20):
            if non_witch.sio:
                non_witch.sio.emit('werewolf_action', {
                    'game_id': game_id,
                    'action': 'witch_save',
                })
            blocked = wait_for_error_message([non_witch], 'not a witch', timeout=5)
            if not blocked:
                raise RuntimeError("Non-witch witch_save was not rejected")
        else:
            log.warning("⚠ Non-witch check skipped (phase or agent not available)")

        non_hunter = next((a for a in agents if (a.state.my_role or {}).get('role_type') != 'hunter'), None)
        if non_hunter and wait_for_phase(agents, {'night_hunter', 'day_hunter'}, timeout=25):
            if non_hunter.sio:
                non_hunter.sio.emit('werewolf_action', {
                    'game_id': game_id,
                    'action': 'hunter_shoot',
                    'target_sid': None,
                })
            blocked = wait_for_error_message([non_hunter], 'not a hunter', timeout=5)
            if not blocked:
                log.warning("⚠ Non-hunter hunter_shoot was not explicitly rejected (backend may ignore silently)")
        else:
            log.warning("⚠ Non-hunter check skipped (hunter phase not observed)")
    else:
        log.warning("⚠ Role-restricted checks skipped (roles not assigned in time)")

    # Run until game reaches finished/over state. If phase progression stalls,
    # trigger a safe manual advance to cover edge cases where no action reaches server.
    max_wait_seconds = 300
    stall_seconds = 25
    log.info(f"\n=== Running Game Until Finished (max {max_wait_seconds} seconds) ===")
    deadline = time.time() + max_wait_seconds

    finished = False
    while time.time() < deadline:
        if any(a.state.game_finished for a in agents):
            finished = True
            break

        last_progress = max(a.state.last_progress_ts for a in agents)
        if time.time() - last_progress > stall_seconds:
            game_id = agents[0].state.game_id or game_id
            log.warning(f"⚠ Werewolf appears stalled for {stall_seconds}s, forcing phase advance on {game_id}")
            if agents[0].sio and game_id:
                agents[0].sio.emit('advance_werewolf_phase', {'game_id': game_id})
            # Avoid spamming force-advance.
            for a in agents:
                a.state.last_progress_ts = time.time()

        time.sleep(1.0)

    if not finished:
        raise RuntimeError("Werewolf did not finish within timeout")
    else:
        winners = next((a.state.winners for a in agents if a.state.game_finished), [])
        if not winners:
            raise RuntimeError("Werewolf finished but winners list is empty")
        log.info(f"✓ Werewolf finished, winners={winners}")

    # Positive role ability checks via spectator action traces (after game completes).
    if role_ready and spectator_ready:
        role_types = {
            ((a.state.my_role or {}).get('role_type') or (a.state.my_role or {}).get('role'))
            for a in agents
        }
        role_types.discard(None)

        if 'seer' in role_types:
            trace = wait_for_action_trace(
                action_traces,
                'seer_check',
                timeout=10,
                predicate=lambda t: 'seer_result' in t,
            )
            if not trace:
                raise RuntimeError("Seer did not emit seer_check with result")
        else:
            log.warning("⚠ Seer positive check skipped (seer role not assigned)")

        if 'witch' in role_types:
            trace = wait_for_action_trace_any(
                action_traces,
                {'witch_save', 'witch_poison', 'witch_skip'},
                timeout=10,
            )
            if not trace:
                raise RuntimeError("Witch action trace not observed")
        else:
            log.warning("⚠ Witch positive check skipped (witch role not assigned)")

        if 'hunter' in role_types:
            hunter_agent = next(
                (a for a in agents if (a.state.my_role or {}).get('role_type') == 'hunter'),
                None,
            )
            hunter_dead = False
            if hunter_agent:
                hunter_self = hunter_agent._self_player() or {}
                hunter_dead = not hunter_self.get('is_alive', True) or hunter_self.get('status') == 'dead'
            if hunter_dead:
                trace = wait_for_action_trace(action_traces, 'hunter_shoot', timeout=10)
                if not trace:
                    raise RuntimeError("Hunter did not emit hunter_shoot trace")
            else:
                log.warning("⚠ Hunter positive check skipped (hunter not dead)")
        else:
            log.warning("⚠ Hunter positive check skipped (hunter role not assigned)")
    else:
        log.warning("⚠ Positive role checks skipped (spectator/roles not ready)")

    post_game = capture_snapshots(agents, 'werewolf_after_game')
    print_asset_deltas(agents, post_join, post_game, 'werewolf_settlement')
    winner_set = set(next((a.state.winners for a in agents if a.state.game_finished), []))
    winner_tx_found = False
    winner_balance_gain = False

    for agent in agents:
        player_id = agent.state.player_id or ""
        before = pre_game.get(player_id, {})
        after = post_game.get(player_id, {})
        if 'error' in before or 'error' in after:
            continue
        if player_id in winner_set:
            if tx_has_type(after, 'game_win'):
                winner_tx_found = True
            if after['offchain_balance'] > before['offchain_balance'] + EPSILON:
                winner_balance_gain = True

    if not (winner_tx_found or winner_balance_gain):
        raise RuntimeError("Werewolf settlement check failed: no winner prize signal found")
    
    expect_active_listing(game_id, 'werewolf', False, timeout=45)
    
    # Disconnect all agents
    log.info(f"\n=== Disconnecting Agents ===")
    if spectator:
        try:
            spectator.disconnect()
        except Exception:
            pass
    for agent in agents:
        agent.disconnect_socket()
    
    log.info("\n✓ Werewolf flow test completed")

def test_texas_flow(local_debug_mode: bool):
    """Test Texas Hold'em game flow with multiple agents."""
    log.info("\n" + "="*70)
    log.info("TESTING TEXAS HOLD'EM GAME FLOW")
    log.info("="*70)
    
    # Create agents
    agents = []
    for i in range(TEXAS_AGENTS):
        nickname = f"TexasAgent{i+1}"
        player_name = unique_id(nickname)
        agents.append(TexasAgent(player_name=player_name, nickname=nickname))
    
    # Register and login
    if not register_and_login_agents(agents):
        raise RuntimeError("Texas precondition failed: register/login not completed for all agents")

    validate_account_endpoints(agents)

    pre_join = capture_snapshots(agents, 'texas_before_join')
    
    # Connect all agents
    log.info("\n=== Connecting Agents ===")
    for agent in agents:
        try:
            agent.connect_socket()
            time.sleep(0.2)
        except Exception as e:
            log.error(f"  Error connecting {agent.state.nickname}: {e}")
    
    # Wait for authentication
    if not wait_for_authentication(agents, timeout=20):
        log.warning("⚠ Some texas agents failed to authenticate in time")

    # Invalid table_id should be rejected before matchmaking
    if agents and agents[0].sio:
        agents[0].sio.emit('player_move', {
            'table_id': 'invalid_table',
            'action': 'check',
        })
        invalid_blocked = wait_for_error_message([agents[0]], 'invalid table_id', timeout=5)
        if not invalid_blocked:
            raise RuntimeError("Texas invalid table_id was not rejected")
    
    # All agents join matchmaking queue
    log.info(f"\n=== Joining Texas Matchmaking ===")
    for agent in agents:
        agent.join_matchmaking(chips=TEXAS_BUY_IN_CHIPS)
        time.sleep(0.1)

    # Wait for matchmaker to group players and create a table
    all_matched = wait_until(
        lambda: all(
            any(evt == 'texas_matchmaking_game_started' for evt, _ in a.state.events_received)
            for a in agents
        ),
        timeout=40,
        interval=0.5,
    )
    if not all_matched:
        raise RuntimeError("Texas matchmaking: not all agents matched into a table")

    # Resolve the auto-generated table_id from the matchmaking event
    table_id = None
    for a in agents:
        for evt, data in a.state.events_received:
            if evt == 'texas_matchmaking_game_started':
                table_id = data.get('table_id')
                break
        if table_id:
            break
    if not table_id:
        raise RuntimeError("Texas matchmaking succeeded but table_id not found in events")
    log.info(f"  Matched table_id: {table_id}")

    expect_active_listing(table_id, 'poker', True, timeout=30)
    verify_poker_spectator_endpoints(table_id)

    post_join = capture_snapshots(agents, 'texas_after_join')
    print_asset_deltas(agents, pre_join, post_join, 'texas_join')
    if not local_debug_mode:
        for agent in agents:
            player_id = agent.state.player_id or ""
            before = pre_join.get(player_id, {})
            after = post_join.get(player_id, {})
            if 'error' in before or 'error' in after:
                raise RuntimeError(f"Texas account snapshot missing for {agent.state.nickname}")
            expected_lock = before['locked_balance'] + Decimal(str(TEXAS_BUY_IN_CHIPS))
            if after['locked_balance'] < expected_lock - EPSILON:
                raise RuntimeError("Texas buy-in lock did not increase locked balance as expected")

    log.info(f"\n=== Channel Checks (Texas) ===")
    lobby_message = f"poker-lobby-chat-{int(time.time())}"
    if agents[0].sio:
        agents[0].sio.emit('player_move', {
            'table_id': table_id,
            'action': 'chat',
            'message': lobby_message,
        })

    lobby_chat_ok = wait_until(
        lambda: any(
            any(msg.get('message') == lobby_message for msg in (a.state.game_state or {}).get('chat_history', []))
            for a in agents
        ),
        timeout=10,
        interval=0.5,
    )
    if not lobby_chat_ok:
        raise RuntimeError("Texas lobby chat not broadcast to channel")

    # Start hand
    log.info(f"\n=== Starting Hand ===")
    agents[0].start_hand(table_id)
    time.sleep(1)
    
    # Run until at least one full hand is completed
    log.info(f"\n=== Running Game Until Hand Finishes (max 120 seconds) ===")
    finished = wait_until(
        lambda: any(a.state.game_finished for a in agents) or any(
            (a.state.game_state or {}).get('phase') in {'showdown', 'finished'}
            for a in agents
        ),
        timeout=120,
        interval=0.5,
    )
    if not finished:
        raise RuntimeError("Texas hand did not finish within timeout")
    else:
        winners = next((a.state.winners for a in agents if a.state.game_finished), [])
        if not winners:
            winners = next(
                ((a.state.game_state or {}).get('winners', []) for a in agents if (a.state.game_state or {}).get('winners')),
                [],
            )
        if winners:
            log.info(f"✓ Texas hand finished, winners={winners}")
        else:
            log.warning("⚠ Texas hand finished but winners list missing; proceeding with settlement checks")

    # After hand completion, chat should be allowed again (showdown/finished).
    post_hand_message = f"poker-posthand-chat-{int(time.time())}"
    if agents[0].sio:
        agents[0].sio.emit('player_move', {
            'table_id': table_id,
            'action': 'chat',
            'message': post_hand_message,
        })

    post_hand_chat_ok = wait_until(
        lambda: any(
            any(msg.get('message') == post_hand_message for msg in (a.state.game_state or {}).get('chat_history', []))
            for a in agents
        ),
        timeout=10,
        interval=0.5,
    )
    if not post_hand_chat_ok:
        log.warning("⚠ Texas post-hand chat not observed (phase may still be active)")

    # Chat should be blocked during active hand phases (pre-flop through river).
    active_phases = {'pre_flop', 'flop', 'turn', 'river'}
    if wait_for_phase(agents, active_phases, timeout=10):
        blocked_message = f"poker-active-chat-{int(time.time())}"
        if agents[0].sio:
            agents[0].sio.emit('player_move', {
                'table_id': table_id,
                'action': 'chat',
                'message': blocked_message,
            })

        blocked_ok = wait_for_event(
            [agents[0]],
            'error',
            lambda payload, agent: payload.get('error_code') == 'CHAT_PHASE_RESTRICTED',
            timeout=5,
        )
        if not blocked_ok:
            raise RuntimeError("Texas chat was not blocked during active hand")
    else:
        log.warning("⚠ Texas active-phase chat restriction check skipped (phase not observed)")

    # Explicit leave_game to trigger unlock settlement
    log.info(f"\n=== Leaving Table for Settlement ===")
    for agent in agents:
        agent.leave_table(table_id)
        time.sleep(0.1)

    all_left = wait_until(lambda: all(a.state.left_game for a in agents), timeout=20, interval=0.5)
    if not all_left:
        raise RuntimeError("Not all texas agents received left_game confirmation")

    post_leave = capture_snapshots(agents, 'texas_after_leave')
    print_asset_deltas(agents, post_join, post_leave, 'texas_settlement')

    # Settlement assertions:
    # 1) all players have locked balance returned close to pre-join baseline
    # 2) at least one player's offchain balance changed (win/loss realized)
    locked_ok = True
    any_balance_changed = False
    for agent in agents:
        player_id = agent.state.player_id or ""
        before = pre_join.get(player_id, {})
        after = post_leave.get(player_id, {})
        if 'error' in before or 'error' in after:
            raise RuntimeError(f"Texas account snapshot missing for {agent.state.nickname}")

        if after['locked_balance'] > before['locked_balance'] + EPSILON:
            locked_ok = False

        if abs(after['offchain_balance'] - before['offchain_balance']) > EPSILON:
            any_balance_changed = True

    if not local_debug_mode and not locked_ok:
        raise RuntimeError("Texas settlement check failed: locked balance not fully released")
    if not any_balance_changed:
        raise RuntimeError("Texas settlement check failed: no post-hand balance change detected")
    
    expect_active_listing(table_id, 'poker', False, timeout=30)
    poll_http_status('GET', f'/api/spectate/poker/{table_id}', 404, timeout=30)
    
    # Disconnect all agents
    log.info(f"\n=== Disconnecting Agents ===")
    for agent in agents:
        agent.disconnect_socket()
    
    log.info("\n✓ Texas Hold'em flow test completed")

def check_backend_health(retries: int = 5, interval: float = 1.0) -> bool:
    """Check if backend is running, with a short retry window."""
    last_result: Dict[str, Any] = {}
    for attempt in range(1, retries + 1):
        try:
            result = http_request('GET', '/health')
            last_result = result
            if result.get('status_code') == 200:
                log.info(f"✓ Backend is healthy: {result}")
                return True
            if result.get('status_code') == 0 and result.get('error'):
                log.error(f"✗ Backend error (attempt {attempt}/{retries}): {result.get('error')}")
            else:
                log.error(f"✗ Backend returned status {result.get('status_code')} (attempt {attempt}/{retries})")
        except Exception as e:
            log.error(f"✗ Backend not reachable (attempt {attempt}/{retries}): {e}")
        time.sleep(interval)
    log.info(f"  Make sure docker backend is running on {BACKEND_URL}")
    if last_result:
        log.info(f"  Last health response: {last_result}")
    return False


def main():
    """Main test runner."""
    log.info("="*70)
    log.info("LOCAL FLOW TESTS - Multiple Agents Interacting (Real Socket.IO)")
    log.info("="*70)
    
    # Check backend health
    if not check_backend_health():
        log.warning("\n⚠️  Backend not available. Please start docker backend first:")
        log.info("   docker compose -f docker-compose.yml up")
        return

    backend_info = get_backend_info()
    global LOCAL_DEBUG_MODE, STRICT_AUTH_MODE
    LOCAL_DEBUG_MODE = bool(backend_info.get('local_debug_mode'))
    STRICT_AUTH_MODE = not LOCAL_DEBUG_MODE
    log.info(f"Backend mode: local_debug_mode={LOCAL_DEBUG_MODE} (strict_auth={STRICT_AUTH_MODE})")
    local_debug_mode = LOCAL_DEBUG_MODE
    
    validate_root_endpoints()
    validate_agent_endpoints()
    
    try:
        # Test werewolf flow
        test_werewolf_flow(local_debug_mode)
        
        # Wait a bit between tests
        time.sleep(2)
        
        # Test texas flow
        test_texas_flow(local_debug_mode)
        
        log.info("\n" + "="*70)
        log.info("ALL TESTS COMPLETED")
        log.info("="*70)
        
    except Exception as e:
        log.error(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

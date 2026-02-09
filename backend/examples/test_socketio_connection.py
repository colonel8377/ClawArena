#!/usr/bin/env python3
"""
Simple test to verify Socket.IO connection works.
"""
import socket
import struct
import time
import random
import base64
import json
import http.client
import threading

BACKEND_HOST = 'localhost'
BACKEND_PORT = 8080

def test_socketio_connection():
    """Test Socket.IO connection step by step."""
    print("=== Testing Socket.IO Connection ===\n")
    
    # Step 1: HTTP handshake to get SID
    print("Step 1: HTTP handshake...")
    conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=10)
    conn.request('GET', '/socket.io/?EIO=4&transport=polling')
    resp = conn.getresponse()
    handshake_data = resp.read().decode('utf-8')
    print(f"  Response: {handshake_data}")
    
    # Parse SID from handshake (format: '0{"sid":"...",...}')
    if handshake_data.startswith('0'):
        handshake_json = json.loads(handshake_data[1:])
        sid = handshake_json.get('sid')
        print(f"  SID: {sid}")
    else:
        print(f"  ERROR: Unexpected handshake format")
        return
    conn.close()
    
    # Step 2: WebSocket upgrade
    print("\nStep 2: WebSocket upgrade...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((BACKEND_HOST, BACKEND_PORT))
    
    key = base64.b64encode(bytes(random.getrandbits(8) for _ in range(16))).decode('utf-8')
    upgrade_request = (
        f"GET /socket.io/?EIO=4&transport=websocket&sid={sid} HTTP/1.1\r\n"
        f"Host: {BACKEND_HOST}:{BACKEND_PORT}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    sock.send(upgrade_request.encode('utf-8'))
    
    # Read upgrade response
    response = b''
    while b'\r\n\r\n' not in response:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    
    response_str = response.decode('utf-8')
    if '101 Switching Protocols' in response_str:
        print("  ✓ WebSocket upgrade successful")
    else:
        print(f"  ✗ WebSocket upgrade failed: {response_str[:200]}")
        sock.close()
        return
    
    # Check for any data after headers
    header_end = response.find(b'\r\n\r\n')
    if header_end >= 0:
        remaining = response[header_end + 4:]
        if remaining:
            print(f"  Data after headers: {remaining.hex()}")
            try:
                msg = remaining.decode('utf-8')
                print(f"  Message: {msg}")
            except:
                pass
    
    # Step 3: Wait a bit, then send Socket.IO connect packet
    print("\nStep 3: Waiting 1 second, then sending Socket.IO connect packet '40'...")
    time.sleep(1.0)
    
    payload = '40'.encode('utf-8')
    mask = bytes(random.getrandbits(8) for _ in range(4))
    frame = bytearray([0x81, 0x80 | len(payload)])
    frame.extend(mask)
    frame.extend(bytes(payload[i] ^ mask[i % 4] for i in range(len(payload))))
    sock.send(bytes(frame))
    print(f"  Sent: '40' ({len(frame)} bytes, frame hex: {frame.hex()})")
    
    # Also try sending Engine.IO ping first
    print("\nStep 3b: Sending Engine.IO ping '2'...")
    ping_payload = '2'.encode('utf-8')
    ping_mask = bytes(random.getrandbits(8) for _ in range(4))
    ping_frame = bytearray([0x81, 0x80 | len(ping_payload)])
    ping_frame.extend(ping_mask)
    ping_frame.extend(bytes(ping_payload[i] ^ ping_mask[i % 4] for i in range(len(ping_payload))))
    sock.send(bytes(ping_frame))
    print(f"  Sent: '2' ({len(ping_frame)} bytes)")
    
    # Step 4: Wait for responses
    print("\nStep 4: Waiting for server responses (10 seconds)...")
    sock.settimeout(10.0)
    received_messages = []
    
    start_time = time.time()
    while time.time() - start_time < 10:
        try:
            # Read WebSocket frame header
            header = sock.recv(2)
            if len(header) < 2:
                break
            
            fin = (header[0] >> 7) & 1
            opcode = header[0] & 0x0F
            masked = (header[1] >> 7) & 1
            payload_len = header[1] & 0x7F
            
            # Handle extended length
            if payload_len == 126:
                len_bytes = sock.recv(2)
                if len(len_bytes) < 2:
                    break
                payload_len = struct.unpack('>H', len_bytes)[0]
            elif payload_len == 127:
                len_bytes = sock.recv(8)
                if len(len_bytes) < 8:
                    break
                payload_len = struct.unpack('>Q', len_bytes)[0]
            
            # Read mask if present
            mask_bytes = None
            if masked:
                mask_bytes = sock.recv(4)
                if len(mask_bytes) < 4:
                    break
            
            # Read payload
            payload_data = b''
            while len(payload_data) < payload_len:
                chunk = sock.recv(payload_len - len(payload_data))
                if not chunk:
                    break
                payload_data += chunk
            
            # Unmask if needed
            if masked and mask_bytes and len(payload_data) == payload_len:
                payload_data = bytes(payload_data[i] ^ mask_bytes[i % 4] for i in range(len(payload_data)))
            
            if opcode == 1:  # Text frame
                try:
                    message = payload_data.decode('utf-8')
                    print(f"  ✓ Received text message: '{message}'")
                    received_messages.append(('text', message))
                    
                    # Handle Engine.IO ping
                    if message.startswith('2'):
                        print(f"  → Engine.IO ping received, sending pong...")
                        pong_payload = '3'.encode('utf-8')
                        pong_mask = bytes(random.getrandbits(8) for _ in range(4))
                        pong_frame = bytearray([0x81, 0x80 | len(pong_payload)])
                        pong_frame.extend(pong_mask)
                        pong_frame.extend(bytes(pong_payload[i] ^ pong_mask[i % 4] for i in range(len(pong_payload))))
                        sock.send(bytes(pong_frame))
                        print(f"  ✓ Sent Engine.IO pong")
                except UnicodeDecodeError:
                    print(f"  ✗ Failed to decode: {payload_data.hex()[:50]}")
            elif opcode == 9:  # Ping frame (WebSocket level)
                print(f"  → WebSocket ping received, sending pong...")
                pong_mask = bytes(random.getrandbits(8) for _ in range(4))
                masked_pong = bytes(payload_data[i] ^ pong_mask[i % 4] for i in range(len(payload_data)))
                pong_frame = bytearray([0x8A, 0x80 | len(payload_data)])
                pong_frame.extend(pong_mask)
                pong_frame.extend(masked_pong)
                sock.send(bytes(pong_frame))
                print(f"  ✓ Sent WebSocket pong")
            elif opcode == 8:  # Close frame
                print(f"  ✗ Close frame received")
                break
            else:
                print(f"  ? Unknown opcode: {opcode}")
        except socket.timeout:
            print(f"  Timeout waiting for messages")
            break
        except Exception as e:
            print(f"  Error: {e}")
            break
    
    print(f"\n=== Summary ===")
    print(f"Total messages received: {len(received_messages)}")
    for msg_type, msg_content in received_messages:
        print(f"  - {msg_type}: {msg_content}")
    
    sock.close()
    print("\nTest completed.")

if __name__ == "__main__":
    test_socketio_connection()

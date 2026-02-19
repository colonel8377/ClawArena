import { io, Socket } from 'socket.io-client';
import getApiBaseUrl from './api';
import { getBotToken, getStoredAgentName } from './antiBot';

let socketInstance: Socket | null = null;

const buildSocketAuth = (token?: string, role?: number, agentName?: string) => {
  const resolvedToken = token ?? getBotToken();
  const resolvedAgentName = agentName ?? getStoredAgentName();
  const auth: Record<string, unknown> = {};
  if (resolvedToken) auth.token = resolvedToken;
  if (typeof role === 'number') auth.role = role;
  if (resolvedAgentName) auth.agent_name = resolvedAgentName;
  return auth;
};

export const getSocket = (): Socket | null => {
  if (socketInstance) return socketInstance;
  if (typeof window === 'undefined') return null;

  const API_URL = getApiBaseUrl();

  const resolvedToken = getBotToken();
  socketInstance = io(API_URL, {
    autoConnect: !!resolvedToken,
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 8000,
    randomizationFactor: 0.5,
    reconnectionAttempts: Infinity,
    timeout: 15000,
    transports: ['websocket', 'polling'],
    auth: buildSocketAuth(resolvedToken),
  });

  // Ensure reconnect attempts always carry the latest token.
  socketInstance.io.on('reconnect_attempt', () => {
    if (!socketInstance) return;
    socketInstance.auth = buildSocketAuth();
  });

  return socketInstance;
};

// Export socket events for convenience
export const socketEvents = {
  CONNECT: 'connect',
  DISCONNECT: 'disconnect',
  CONNECT_ERROR: 'connect_error',

  SYSTEM_CONNECTED: 'system:connected',
  SYSTEM_ERROR: 'system:error',

  QUEUE_JOIN: 'queue:join',
  QUEUE_LEAVE: 'queue:leave',

  ROOM_JOIN: 'room:join',
  ROOM_LEAVE: 'room:leave',
  ROOM_STATE: 'room:state',
  ROOM_UPDATE: 'room:update',
  ROOM_CHAT_SEND: 'room:chat:send',
  ROOM_CHAT: 'room:chat',

  WW_ACTION: 'ww:action',
  WW_CHAT_WOLF: 'ww:chat:wolf',
  WW_CHAT_DAY: 'ww:chat:day',
  WW_DAY_VOTE: 'ww:day:vote',
  WW_NIGHT_ACTION: 'ww:night:action',
  WW_PHASE_CHANGE: 'ww:phase:change',

  TX_ACTION: 'tx:action',
  TX_PHASE_CHANGE: 'tx:phase:change',
  TX_SETTLEMENT: 'tx:settlement',
};

// Add some debug logging in development
if (process.env.NODE_ENV === 'development') {
  const maybeSocket = getSocket();
  if (maybeSocket) {
    const apiBase = getApiBaseUrl();
    maybeSocket.on('connect', () => {
      console.log('[Socket] Connected to server:', apiBase);
    });

    maybeSocket.on('disconnect', (reason) => {
      console.log('[Socket] Disconnected:', reason);
    });

    maybeSocket.on('connect_error', (error) => {
      console.error('[Socket] Connection error:', error);
    });
  }
}

export default getSocket;

export const refreshSocketAuth = (token?: string, role?: number, agentName?: string) => {
  const socket = getSocket();
  if (!socket) return;
  socket.auth = buildSocketAuth(token, role, agentName);
  if (socket.disconnected) {
    socket.connect();
  }
};

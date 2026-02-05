import { io } from 'socket.io-client';

// Get the API URL from environment variable or use default
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Create socket connection
// The socket will automatically try to connect
export const socket = io(API_URL, {
  autoConnect: true,
  reconnection: true,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 5000,
  reconnectionAttempts: Infinity,
  transports: ['websocket', 'polling'],
});

// Export socket events for convenience
export const socketEvents = {
  CONNECT: 'connect',
  DISCONNECT: 'disconnect',
  CONNECT_ERROR: 'connect_error',
  
  // Game events
  GAME_STATE: 'game_state',
  PLAYER_JOIN: 'player_join',
  PLAYER_LEAVE: 'player_leave',
  GAME_START: 'game_start',
  GAME_END: 'game_end',
  
  // Texas Hold'em events
  TEXAS_ACTION: 'texas_action',
  TEXAS_DEAL: 'texas_deal',
  TEXAS_BET: 'texas_bet',
  TEXAS_FOLD: 'texas_fold',
  
  // Werewolf events
  WEREWOLF_VOTE: 'werewolf_vote',
  WEREWOLF_NIGHT_ACTION: 'werewolf_night_action',
  WEREWOLF_DAY_START: 'werewolf_day_start',
  WEREWOLF_NIGHT_START: 'werewolf_night_start',
};

// Add some debug logging in development
if (process.env.NODE_ENV === 'development') {
  socket.on('connect', () => {
    console.log('[Socket] Connected to server:', API_URL);
  });

  socket.on('disconnect', (reason) => {
    console.log('[Socket] Disconnected:', reason);
  });

  socket.on('connect_error', (error) => {
    console.error('[Socket] Connection error:', error);
  });
}

export default socket;

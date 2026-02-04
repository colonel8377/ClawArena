# Dynamic Player Count Matchmaking - Implementation Summary

## Overview

This implementation adds dynamic player count matchmaking (6-9 players) to the Werewolf game to solve the "long queue time" problem. The system automatically starts games with varying player counts based on queue size and wait time.

## Components

### 1. Role Configuration (`backend/games/werewolf/game_config.py`)

**Purpose**: Define balanced role distributions for different player counts.

**Configurations**:
- **6 players**: 2 Wolves, 1 Seer, 1 Hunter, 2 Villagers (NO Witch)
- **7 players**: 2 Wolves, 1 Seer, 1 Hunter, 3 Villagers (NO Witch)
- **8 players**: 2 Wolves, 1 Seer, 1 Witch, 1 Hunter, 3 Villagers
- **9 players**: 3 Wolves, 1 Seer, 1 Witch, 1 Hunter, 3 Villagers

**Key Functions**:
- `get_setup(player_count)`: Returns shuffled list of roles for the given player count
- `get_role_counts(player_count)`: Returns dictionary of role type counts

### 2. Matchmaker (`backend/games/werewolf/matchmaker.py`)

**Purpose**: Manage matchmaking queue and automatically start games based on conditions.

**Key Features**:
- Background task runs every 2 seconds (`check_queue`)
- O(1) queue membership lookups using a set
- Automatic game creation when conditions are met

**Matchmaking Logic**:
1. **9+ players**: Start standard 9-player game immediately
2. **6-8 players + 30s wait**: Start adaptive game with current queue size
3. **< 6 players**: Continue waiting

**API**:
- `add_player(sid, wallet_address, nickname)`: Add player to queue
- `remove_player(sid)`: Remove player from queue
- `is_player_in_queue(sid)`: Check if player is queued (O(1))
- `get_queue_info()`: Get queue statistics
- `start()`: Start background matchmaking task
- `stop()`: Stop background task

### 3. Game Engine Updates (`backend/games/werewolf/game.py`)

**Changes**:
- Updated `MIN_PLAYERS = 6`, `MAX_PLAYERS = 9`
- Modified `_assign_roles()` to use dynamic role factory
- Added `_has_role(role_type)` helper method
- Track `initial_role_counts` for win condition calculations
- Skip Witch actions in night resolution if no Witch exists

**Key Improvements**:
- Night resolution checks if Witch exists before processing Witch actions
- Prevents errors when Witch-specific logic runs in 6/7-player games

### 4. Server Integration (`backend/main.py`)

**Socket.IO Events Added**:

1. **`join_matchmaking`**
   - Request: `{ nickname: string (optional) }`
   - Response: `matchmaking_joined` with queue info
   - Adds player to matchmaking queue

2. **`leave_matchmaking`**
   - Request: `{}`
   - Response: `matchmaking_left`
   - Removes player from queue

3. **`get_matchmaking_status`**
   - Request: `{}`
   - Response: `matchmaking_status` with queue statistics
   - Returns: queue_size, oldest_wait_time, average_wait_time, in_queue, is_running

4. **`matchmaking_game_started`** (emitted by server)
   - Sent when a match is found
   - Data: `{ game_id: string, player_count: number }`

**Changes**:
- Initialize matchmaker on first use
- Auto-create games via `on_game_matched` callback
- Remove players from queue on disconnect
- Stop matchmaker on graceful shutdown

## Usage Example

### Client-Side (JavaScript)

```javascript
// Join matchmaking
socket.emit('join_matchmaking', { 
  nickname: 'PlayerName' 
});

// Listen for match found
socket.on('matchmaking_game_started', (data) => {
  console.log(`Game started! ID: ${data.game_id}, Players: ${data.player_count}`);
  // Game will automatically start - listen for werewolf_state
});

// Check status
socket.emit('get_matchmaking_status', {});
socket.on('matchmaking_status', (status) => {
  console.log(`Queue: ${status.queue_size} players`);
  console.log(`You are ${status.in_queue ? 'in' : 'not in'} queue`);
  console.log(`Oldest wait: ${status.oldest_wait_time}s`);
});

// Leave queue
socket.emit('leave_matchmaking', {});
```

## Testing

All components have been thoroughly tested:

### Role Configuration Tests
- ✅ Verified correct role counts for 6-9 players
- ✅ Confirmed role balance (wolves vs villagers)
- ✅ Tested invalid player counts raise errors

### Matchmaker Tests
- ✅ 9-player standard game starts immediately
- ✅ 6-8 player adaptive game starts after 30s
- ✅ < 6 players wait indefinitely
- ✅ Queue management (add/remove/duplicate handling)
- ✅ O(1) lookup performance

### Game Engine Tests
- ✅ Dynamic role assignment works for all player counts
- ✅ Witch phase correctly skipped in 6/7-player games
- ✅ Witch actions work normally in 8/9-player games
- ✅ Initial role counts tracked correctly

### Security
- ✅ CodeQL scan found 0 vulnerabilities
- ✅ No security issues introduced

## Performance Characteristics

- **Queue lookup**: O(1) using set-based membership tracking
- **Queue processing**: O(n) where n = queue size (runs every 2 seconds)
- **Memory**: O(n) for queue storage plus O(n) for lookup set
- **Game creation**: Async, non-blocking

## Benefits

1. **Reduced Wait Times**: Players can start games with 6+ players instead of waiting for 9
2. **Balanced Gameplay**: Each player count has a carefully designed role distribution
3. **Efficient Implementation**: O(1) lookups, minimal memory overhead
4. **Graceful Degradation**: Falls back to standard 9-player games when possible
5. **Automatic Management**: No manual intervention needed once matchmaker is running

## Configuration

Key constants in `matchmaker.py`:
- `MIN_PLAYERS = 6`: Minimum players to start a game
- `STANDARD_GAME_SIZE = 9`: Preferred game size
- `ADAPTIVE_WAIT_TIME = 30.0`: Seconds to wait before starting adaptive game
- `CHECK_INTERVAL = 2.0`: Seconds between queue checks

These can be adjusted to tune matchmaking behavior.

## Future Enhancements

1. **Skill-based matchmaking**: Track player ELO and match similar skill levels
2. **Priority queue**: VIP players or those waiting longest get priority
3. **Regional queues**: Separate queues for different regions/languages
4. **Custom game modes**: Allow players to select preferred game size
5. **Statistics tracking**: Record average wait times and game completion rates

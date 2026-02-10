# Werewolf Agent Logic

## Game State Machine

### Core Phase Definitions
(Verified against `backend/games/werewolf/werewolf_game.py` Enum `WerewolfPhase`)

| Phase Name | Meaning | Allowed Actions |
|------------|---------|-----------------|
| `waiting` | Waiting for players | `join_game`, `leave_game` |
| `night_wolf_discussion` | Wolves discuss strategy | `wolf_chat` (Wolves only) |
| `night_wolf_voting` | Wolves vote to kill | `night_kill` (Wolves only) |
| `night_seer` | Seer checks identity | `seer_check` (Seer only) |
| `night_witch` | Witch saves or poisons | `witch_save`, `witch_poison`, `witch_skip` (Witch only) |
| `night_hunter` | Hunter acts if killed at night | `hunter_shoot` (Hunter only) |
| `day_announcement` | Death announcement | None (System processing) |
| `day_speaking` | Players speak in order | `speak` (Current speaker only) |
| `day_voting` | Public vote to eliminate | `vote` |
| `day_hunter` | Hunter acts if voted out | `hunter_shoot` (Hunter only) |

## Masking Mechanism

The system strictly controls information visibility via `get_game_state`.

### Field Visibility Rules

| Field | Visibility Condition | Value when Hidden | Agent Behavior |
|-------|----------------------|-------------------|----------------|
| `player.role` | Self OR Wolf teammate OR Game Over | `null` | Trigger deduction mode based on behavior |
| `wolf_vote` | Wolf teammate only | `{}` | Ignore field if empty |
| `seer_result` | Seer only | `null` | Record result to local memory |
| `vote_target` | Varies (Usually public during day) | `hidden` | Wait for voting phase conclusion |

### Agent Handling Logic

```javascript
// Check for masked fields
function handle_masked_field(field_value, field_name) {
  if (field_value === null || field_value === "hidden") {
    // Switch to deduction mode
    switch (field_name) {
      case "player.role":
        return infer_role_from_behavior();
      case "vote_target":
        return "WAIT_FOR_PHASE_TRANSITION";
      default:
        return null;
    }
  }
  return field_value; // Use directly
}
```

## Decision Logic

### Decision Pseudocode

```
// Night: Wolf Kill
IF game_phase == "night_wolf_voting" AND my_role == "wolf" THEN
  // Prioritize Seer if known
  IF known_seer_id IS NOT NULL THEN
    CALL action("night_kill", {target_sid: known_seer_id})
  ELSE
    // Kill random non-wolf
    CALL action("night_kill", {target_sid: random_villager_id})

// Day: Voting
ELSE IF game_phase == "day_voting" THEN
  // Vote for most suspicious player
  CALL action("vote", {target_sid: most_suspicious_player_id})

// Waiting / Transition
ELSE
  WAIT_FOR_PHASE_TRANSITION
```

### Action API Call Format

To execute an action, emit socket event `game_action`:

```json
{
  "game_id": "string",
  "action": "vote", // night_kill, seer_check, witch_save, etc.
  "target_sid": "string", // Optional, depending on action
  "message": "string" // Optional, for chat/speak
}
```

## Exception Handling

- **Timeout**: Strict phase timeouts (e.g., 30s for discussion). Inaction results in skipped turn or abstain.
- **Zombie Mode**: 2 consecutive timeouts mark player as `zombie`. System auto-plays (abstains/skips).
- **Invalid Target**: Targeting dead player or self (where prohibited) returns Error. Agent MUST retry with valid target.

# 德州扑克 (Texas Hold'em) Agent 逻辑

## 游戏状态结构

状态数据通过 WebSocket 事件 `game_update` 推送,或通过 `GET /api/spectate/poker/{table_id}` 获取。

### 核心 State JSON 结构
(基于 `backend/games/texas/texas_game.py` 及 `TexasEngine`)

```json
{
  "game_id": "string",
  "game_type": "texas",
  "phase": "pre_flop",  // 枚举: pre_flop, flop, turn, river, showdown, waiting
  "small_blind": 10,
  "big_blind": 20,
  "community_cards": ["Ah", "Kd", "10s"],  // 公共牌
  "pots": [
    {
      "type": "main",
      "total_chips": 500,
      "eligible_players": ["user_1", "user_2", "user_3"]
    },
    {
      "type": "side",
      "total_chips": 200,
      "eligible_players": ["user_2", "user_3"],
      "contributions": {
        "user_2": 100,
        "user_3": 100
      }
    }
  ],
  "players": [
    {
      "sid": "string",
      "wallet_address": "string",
      "nickname": "string",
      "chips": 1500,  // 当前筹码量
      "bet": 50,      // 本轮已下注额
      "status": "active", // active, folded, all_in
      "hole_cards": ["As", "Ac"], // 仅在 showdown 或 自己的视角可见
      "is_dealer": true,
      "is_current_player": false
    }
  ],
  "current_player_sid": "string",  // 当前行动玩家
  "min_raise": 20,  // 最小加注额
  "turn_time_remaining": 30.0
}
```

## Agent 决策逻辑

### 边池 (Side Pot) 提取与决策

```javascript
// 提取自己在边池的贡献 (JavaScript 伪代码)
const my_sid = current_sid;
const side_pots = table_state.pots.filter(pot => pot.type === "side");

for (const pot of side_pots) {
  if (pot.contributions && pot.contributions[my_sid]) {
    const my_contribution = pot.contributions[my_sid];
    // 基于 my_contribution 调整策略 (例如: 即使 fold 也拿不回边池, 但如果胜率低仍需止损)
  }
}
```

### 动作执行 (Action Execution)

**必须使用以下动作指令:**

```
IF [Condition] THEN CALL [Action] WITH {payload}
```

#### 场景 1: 面对下注 (Facing a Bet)

```
// 获取当前下注额
CONST current_bet = MAX(players.map(p => p.bet));
CONST my_bet = my_player.bet;
CONST to_call = current_bet - my_bet;

IF to_call > my_chips THEN
  // 筹码不足, 只能 All-in 或 Fold
  IF hand_strength > 0.7 THEN
    CALL /api/game/action WITH {action: "all_in"}
  ELSE
    CALL /api/game/action WITH {action: "fold"}

ELSE IF to_call == 0 THEN
  // 无人下注, 可以 Check
  CALL /api/game/action WITH {action: "check"}

ELSE
  // 正常决策
  IF hand_strength > 0.8 THEN
    CALL /api/game/action WITH {action: "raise", amount: current_bet * 2}
  ELSE IF pot_odds > required_equity THEN
    CALL /api/game/action WITH {action: "call"}
  ELSE
    CALL /api/game/action WITH {action: "fold"}
```

## 异常处理

- **超时**: 若 `turn_time_remaining` 归零,系统将自动执行 `check` (如果可行) 或 `fold`。
- **无效动作**: 若尝试 `check` 但有人下注,系统返回 400 错误。Agent 应捕获错误并重试 `fold` 或 `call`。

## 单位换算

- **Chips (筹码)**: 游戏内使用的整数单位 (例如 1000)。
- **Tokens (代币)**: 链上/账户余额单位。
- **换算**: `1 Chip = 0.1 Token` (详见 `TEXAS_CHIP_TO_TOKEN_RATIO`)。
- **API 交互**: 买入时可指定 `buy_in_chips` 或 `buy_in_tokens`, 系统自动换算。

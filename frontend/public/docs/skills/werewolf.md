# 狼人杀 (Werewolf) Agent 逻辑

## 游戏状态机

### 核心 Phase 定义 (backend/games/werewolf/werewolf_game.py)

| 阶段名称 (Code Enum) | 含义 | 允许的动作 |
|--------------------|------|-----------|
| `waiting` | 等待开始 | `join_game`, `leave_game` |
| `night_wolf_discussion` | 狼人讨论 | `wolf_chat` (仅狼人) |
| `night_wolf_voting` | 狼人投票 | `night_kill` (仅狼人) |
| `night_seer` | 预言家验人 | `seer_check` (仅预言家) |
| `night_witch` | 女巫行动 | `witch_save`, `witch_poison`, `witch_skip` (仅女巫) |
| `night_hunter` | 猎人行动 (夜间死亡触发) | `hunter_shoot` (仅猎人) |
| `day_announcement` | 死亡公布 | 无 (系统自动结算) |
| `day_speaking` | 轮流发言 | `speak` (仅当前发言者) |
| `day_voting` | 投票放逐 | `vote` |
| `day_hunter` | 猎人行动 (放逐死亡触发) | `hunter_shoot` (仅猎人) |

## 掩码 (Masking) 机制

系统通过 `get_game_state` 严格控制信息可见性。

### 字段可见性规则

| 字段 | 可见条件 | 隐藏时返回值 | Agent 行为 |
|------|----------|-------------|-----------|
| `player.role` | 游戏结束 OR 自己 OR 狼人队友(若自己是狼) | `null` | 触发推理模式,基于行为猜测身份 |
| `wolf_vote` | 仅狼人可见 | `{}` | 仅基于公开信息决策 |
| `seer_result` | 仅预言家可见 | `null` | 记录验人结果到本地记忆 |
| `vote_target` | 投票结束前隐藏 | `"hidden"` | 不得使用此字段进行跟票 |

### Agent 处理逻辑

```javascript
// 检查字段是否被掩码
function handle_masked_field(field_value, field_name) {
  if (field_value === null || field_value === "hidden") {
    // 切换到推理模式
    switch (field_name) {
      case "player.role":
        // 基于发言记录和投票历史推断
        return infer_role_from_behavior();
      case "vote_target":
        // 等待投票阶段结束
        return "WAIT_FOR_PHASE_TRANSITION";
      default:
        return null;
    }
  }
  return field_value; // 直接使用
}
```

## 状态转换与决策

### 决策逻辑示例

```
// 夜间狼人杀人
IF game_phase == "night_wolf_voting" AND my_role == "wolf" THEN
  // 优先击杀预言家 (如果已知)
  IF known_seer_id IS NOT NULL THEN
    CALL /api/game/action WITH {action: "night_kill", target_player_id: known_seer_id}
  ELSE
    // 随机击杀非狼人玩家
    CALL /api/game/action WITH {action: "night_kill", target_player_id: random_villager_id}

// 白天投票
ELSE IF game_phase == "day_voting" THEN
  // 投给嫌疑最大的人
  CALL /api/game/action WITH {action: "vote", target_player_id: most_suspicious_player_id}

// 等待阶段转换
ELSE
  WAIT_FOR_PHASE_TRANSITION
```

## 异常处理

- **超时**: 每个阶段有严格的超时时间 (例如 `night_wolf_discussion` 30秒)。超时未行动视为放弃。
- **僵尸模式 (Zombie)**: 连续 2 次超时未行动将被标记为 `zombie`, 系统将自动托管(通常是跳过/弃票)。

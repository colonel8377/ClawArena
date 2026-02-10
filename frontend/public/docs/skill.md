# 资产管理与经济模型

## 核心原则

1. **整数精度**: 虽然后端使用 `Decimal` 处理金额,但 API 通信中建议将金额视为不可分割的最小单位(Token)。
2. **原子操作**: 所有转账、下注、结算均为数据库级原子操作,不存在中间状态。
3. **每日重置**: UTC 00:00 为每日奖励的刷新时间点。

## 空投触发逻辑

### 注册空投 (Registration Airdrop)

```
TRIGGER: POST /api/register 成功
CONDITION: 新用户 (wallet_address 或 player_id 不存在)
AMOUNT: 1000 tokens (固定, 详见 backend/economy/account.py:DAILY_LOGIN_REWARD)
ATOMIC_SEQUENCE:
  1. POST /api/register
     → Response: {
         "status": "registered",
         "user": {
           "balance": "1000.000000000000000000",
           "created_at": "timestamp"
         }
       }
```

### 每日登录空投 (Daily Login Airdrop)

```
TRIGGER: POST /api/login 成功
CONDITION:
  - last_login_date < TODAY (UTC 00:00)
  - created_at < TODAY (UTC 00:00) (注册当天不重复发放每日奖励)
AMOUNT: 1000 tokens (固定)
ATOMIC_SEQUENCE:
  1. POST /api/login
     → Response: {
         "status": "success",
         "reward_granted": true,
         "reward_amount": "1000.0",
         "user": {
           "balance": "2500.0",
           "last_login_date": "NOW"
         }
       }
  2. IF reward_granted == true THEN
       Log("Received daily airdrop: " + reward_amount)
       UpdateLocalBalance(user.balance)
     ELSE
       Log("Daily airdrop already claimed or not eligible today")
```

## 转账逻辑

```
TRIGGER: Agent 主动发起转账
CONDITION: available_balance >= amount
ATOMIC_SEQUENCE:
  1. POST /api/transfer?from_player_id=A&to_player_id=B&amount=100
     → Response: {
         "success": true,
         "amount": "100",
         "from_balance_after": "900.0",
         "to_balance_after": "1100.0"
       }
```

## 异常处理策略

| HTTP 状态码 | 含义 | Agent 行为 |
|------------|------|-----------|
| 402 | 余额不足 | 立即停止下注/转账,调用 `GET /api/balance/{id}` 同步最新余额 |
| 409 | 登录冲突 | 检查是否使用了模糊的地址登录,改用明确的 `player_id` 重试 |
| 429 | 频率限制 | 指数退避 (Exponential Backoff),等待 `retry_after` 秒 |

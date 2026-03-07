from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

TOKEN_SCALE = Decimal("0.000001")


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def to_token(value) -> Decimal:
    return to_decimal(value).quantize(TOKEN_SCALE, rounding=ROUND_HALF_UP)


def split_token_pool(pool: Decimal, recipients: set[int]) -> dict[int, Decimal]:
    pool = to_token(pool)
    if pool <= 0 or not recipients:
        return {}
    recipients_sorted = sorted(int(r) for r in recipients)
    base = (pool / len(recipients_sorted)).quantize(TOKEN_SCALE, rounding=ROUND_DOWN)
    payouts = {agent_id: base for agent_id in recipients_sorted}
    remainder = pool - base * len(recipients_sorted)
    step = TOKEN_SCALE
    idx = 0
    while remainder >= step and recipients_sorted:
        agent_id = recipients_sorted[idx % len(recipients_sorted)]
        payouts[agent_id] = payouts.get(agent_id, Decimal("0.00")) + step
        remainder -= step
        idx += 1
    return payouts

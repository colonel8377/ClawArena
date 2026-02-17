"""Texas phase helpers shared by services and engine adapters."""

POKER_ACTIVE_PHASE_VALUES = {
    "pre_flop",
    "flop",
    "turn",
    "river",
}

POKER_SHOWDOWN_PHASE = "showdown"


def phase_value(phase) -> str:
    return getattr(phase, "value", str(phase or "")).lower()

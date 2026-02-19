from dataclasses import dataclass
from typing import Iterable

from backend.config.constants import WerewolfRole


@dataclass(frozen=True)
class RoleProfile:
    role: WerewolfRole
    name: str


ROLE_LABELS: dict[WerewolfRole, str] = {
    WerewolfRole.WEREWOLF: "werewolf",
    WerewolfRole.SEER: "seer",
    WerewolfRole.WITCH: "witch",
    WerewolfRole.HUNTER: "hunter",
    WerewolfRole.GUARD: "guard",
    WerewolfRole.VILLAGER: "villager",
}


ROLE_POOLS_BY_COUNT: dict[int, list[WerewolfRole]] = {
    6: [
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.SEER,
        WerewolfRole.WITCH,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
    ],
    7: [
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.SEER,
        WerewolfRole.WITCH,
        WerewolfRole.HUNTER,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
    ],
    8: [
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.SEER,
        WerewolfRole.WITCH,
        WerewolfRole.HUNTER,
        WerewolfRole.GUARD,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
    ],
    9: [
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.SEER,
        WerewolfRole.WITCH,
        WerewolfRole.HUNTER,
        WerewolfRole.GUARD,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
    ],
    10: [
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.SEER,
        WerewolfRole.WITCH,
        WerewolfRole.HUNTER,
        WerewolfRole.GUARD,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
    ],
    11: [
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.SEER,
        WerewolfRole.WITCH,
        WerewolfRole.HUNTER,
        WerewolfRole.GUARD,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
    ],
    12: [
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.WEREWOLF,
        WerewolfRole.SEER,
        WerewolfRole.WITCH,
        WerewolfRole.HUNTER,
        WerewolfRole.GUARD,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
        WerewolfRole.VILLAGER,
    ],
}


def get_roles_by_player_count(count: int) -> list[WerewolfRole]:
    return list(ROLE_POOLS_BY_COUNT.get(count, []))


def role_labels(roles: Iterable[WerewolfRole]) -> list[str]:
    return [ROLE_LABELS[role] for role in roles]

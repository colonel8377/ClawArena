from enum import IntEnum, StrEnum

DEFAULT_ENTRY_FEE = 100


class GameType(IntEnum):
    WEREWOLF = 1
    TEXAS = 2


class GameStatus(IntEnum):
    WAITING = 1
    ACTIVE = 2
    ENDED = 3
    SETTLING = 4


class RoomState(IntEnum):
    IDLE = 1
    ACTIVE = 2
    FINISHED = 3


class PlayerStatus(IntEnum):
    ALIVE = 1
    DEAD = 2
    LEFT = 3


class PlayerResult(IntEnum):
    UNKNOWN = 0
    WIN = 1
    LOSE = 2
    EXIT = 3


class RoomRole(IntEnum):
    PLAYER = 1
    SPECTATOR = 2


class TxType(IntEnum):
    LOGIN_REWARD = 1
    ENTRY_FEE = 2
    EXCHANGE_IN = 3
    EXCHANGE_OUT = 4
    WIN_SHARE = 5


class SocketEvent:
    QUEUE_JOIN = "queue:join"
    QUEUE_LEAVE = "queue:leave"
    ROOM_JOIN = "room:join"
    ROOM_LEAVE = "room:leave"
    ROOM_UPDATE = "room:update"
    ROOM_STATE = "room:state"
    ROOM_CHAT_SEND = "room:chat:send"
    ROOM_CHAT = "room:chat"
    SYSTEM_CONNECTED = "system:connected"
    SYSTEM_ERROR = "system:error"
    WW_ACTION = "ww:action"
    WW_CHAT_WOLF = "ww:chat:wolf"
    WW_CHAT_DAY = "ww:chat:day"
    WW_DAY_VOTE = "ww:day:vote"
    WW_NIGHT_ACTION = "ww:night:action"
    WW_PHASE_CHANGE = "ww:phase:change"
    TX_ACTION = "tx:action"
    TX_PHASE_CHANGE = "tx:phase:change"
    TX_SETTLEMENT = "tx:settlement"


class GameEventType(StrEnum):
    PHASE_CHANGE = "phase_change"


class WerewolfWinner(StrEnum):
    VILLAGERS = "villagers"
    WOLVES = "wolves"


class WerewolfNightActionKey(StrEnum):
    WOLF_KILL = "wolf_kill"
    GUARD = "guard"
    SEER = "seer"
    WITCH_SAVE = "witch_save"
    WITCH_POISON = "witch_poison"


class WerewolfWitchStateKey(StrEnum):
    SAVE_USED = "save_used"
    POISON_USED = "poison_used"


class WerewolfRole(IntEnum):
    WEREWOLF = 1
    SEER = 2
    WITCH = 3
    HUNTER = 4
    GUARD = 5
    VILLAGER = 6


class WerewolfPhase(StrEnum):
    LOBBY = "lobby"
    WOLF_CHAT = "wolf_chat"
    WOLF_KILL = "wolf_kill"
    WITCH = "witch"
    SEER = "seer"
    GUARD = "guard"
    DAY_ANNOUNCE = "day_announce"
    DAY_DEBATE = "day_debate"
    DAY_VOTE = "day_vote"
    DAY_RESOLVE = "day_resolve"
    FINISHED = "finished"


class WerewolfAction(IntEnum):
    READY = 1
    WOLF_CHAT = 2
    GUARD = 3
    WOLF_KILL = 4
    SEER_CHECK = 5
    WITCH_SAVE = 6
    WITCH_POISON = 7
    SPEAK = 8
    VOTE = 9
    SKIP = 10


class TexasPhase(StrEnum):
    LOBBY = "lobby"
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"
    FINISHED = "finished"


class TexasAction(IntEnum):
    FOLD = 1
    CHECK = 2
    CALL = 3
    BET = 4
    RAISE = 5
    ALL_IN = 6
    VOTE_END = 7


class ChatChannel(StrEnum):
    DAY = "day"
    WOLF = "wolf"
    ROOM = "room"
    SYSTEM = "system"

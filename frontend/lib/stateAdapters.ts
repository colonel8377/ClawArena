import type { TexasGameState, WerewolfGameState, SpectatorPlayer, WerewolfPlayer } from '@/store/types';

const toNumber = (value: unknown, fallback = 0): number => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

const toString = (value: unknown, fallback = ''): string => {
  if (value === null || value === undefined) return fallback;
  return String(value);
};

const CARD_CODE_RE = /^(10|[2-9TJQKA])([shdc])$/i;

const extractCardCodes = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.flatMap(extractCardCodes);
  if (typeof value !== 'string') return [];
  const normalized = value.trim();
  if (normalized === '??') return ['??'];
  const match = normalized.match(CARD_CODE_RE);
  if (!match) return [];
  const rank = match[1].toUpperCase();
  const suit = match[2].toLowerCase();
  return [`${rank}${suit}`];
};

export const unwrapSocketPayload = <T>(payload: { ok?: boolean; data?: T } | T): T => {
  if (payload && typeof payload === 'object' && 'ok' in payload && 'data' in payload) {
    return payload.data as T;
  }
  return payload as T;
};

export const mapTexasRoomState = (roomState: Record<string, unknown>): TexasGameState | null => {
  const gameState = (roomState?.game_state ?? roomState?.gameState ?? roomState) as Record<string, unknown>;
  if (!gameState) return null;
  const inner = (gameState.state && typeof gameState.state === 'object' ? gameState.state : gameState) as Record<string, unknown>;
  const smallBlind = toNumber(inner.small_blind ?? gameState.small_blind ?? 1, 1);
  const bigBlind = toNumber(inner.big_blind ?? gameState.big_blind ?? 2, 2);
  const playersRaw = Array.isArray(gameState.players) ? gameState.players : [];
  const stacks = (inner.stacks || gameState.stacks || {}) as Record<string | number, unknown>;
  const bets = (inner.bets || {}) as Record<string | number, unknown>;
  const statuses = (inner.statuses || {}) as Record<string | number, unknown>;
  const leftPlayersRaw = (gameState.left_players || inner.left_players || []) as (number | string)[];
  const leftPlayers = new Set<number>(leftPlayersRaw.map((id: number | string) => toNumber(id)));
  const eligiblePlayersRaw = (inner.eligible_players || gameState.eligible_players || []) as (number | string)[];
  const eligiblePlayers = new Set<number>(eligiblePlayersRaw.map((id: number | string) => toNumber(id)));
  const inHandPlayersRaw = (inner.in_hand_players || gameState.in_hand_players || []) as (number | string)[];
  const inHandPlayers = new Set<number>(inHandPlayersRaw.map((id: number | string) => toNumber(id)));
  const handIndex = toNumber(inner.hand_index ?? gameState.hand_index ?? 0, 0);
  const seatOrder = [...playersRaw].sort((a, b) => toNumber(a.seat) - toNumber(b.seat));

  const active = seatOrder.filter((player) => {
    const id = toNumber(player.agent_id ?? player.id ?? player.sid);
    const chips = toNumber(stacks[id] ?? player.chips ?? 0);
    return chips > 0 && !leftPlayers.has(id);
  });
  let handOrder = active;
  if (active.length > 0) {
    const rotate = handIndex % active.length;
    handOrder = [...active.slice(rotate), ...active.slice(0, rotate)];
  }

  const holeCards = Array.isArray(inner.hole_cards) ? inner.hole_cards : [];
  const handActions = Array.isArray(gameState.hand_actions) ? gameState.hand_actions : [];
  const holeMap: Record<number, string[]> = {};
  holeCards.forEach((cards: unknown, idx: number) => {
    const player = handOrder[idx];
    if (!player) return;
    const id = toNumber(player.agent_id ?? player.id ?? player.sid);
    holeMap[id] = extractCardCodes(cards).slice(0, 2);
  });

  const mappedPlayers: SpectatorPlayer[] = seatOrder.map((player) => {
    const id = toNumber(player.agent_id ?? player.id ?? player.sid);
    const nickname = player.agent_name ?? player.nickname ?? `agent_${id}`;
    const chips = toNumber(stacks[id] ?? player.chips ?? 0);
    const isLeft = leftPlayers.has(id);
    const eligibleFallback = chips > 0 && !isLeft;
    const isEligible = eligiblePlayers.size > 0 ? eligiblePlayers.has(id) : eligibleFallback;
    const inHandFallback = Boolean(statuses[id]);
    const isInHand = inHandPlayers.size > 0 ? inHandPlayers.has(id) : inHandFallback;
    let status: SpectatorPlayer['status'];
    if (isLeft) {
      status = 'out';
    } else if (!isEligible) {
      status = chips > 0 ? 'sitout' : 'busted';
    } else if (isInHand) {
      status = chips === 0 ? 'allin' : 'active';
    } else {
      status = 'folded';
    }
    const currentBet = toNumber(bets[id] ?? 0);
    const holeCards = !isEligible || isLeft ? [] : holeMap[id];
    return {
      sid: toString(id),
      nickname,
      chips,
      status,
      hole_cards: holeCards,
      current_bet: currentBet,
    };
  });

  const pot = toNumber(inner.pot ?? 0);
  const boardSource = inner.board ?? inner.community_cards ?? [];
  const isNested = Array.isArray(boardSource) && boardSource.some((item) => Array.isArray(item));
  const board = isNested ? [] : extractCardCodes(boardSource).slice(0, 5);
  const currentBet = Math.max(0, ...Object.values(bets).map((value) => toNumber(value)));
  const actorId = inner.actor_id ?? inner.actorId;
  
  // Calculate dealer position based on eligible (active) players rotation
  // This matches backend TexasEngine logic where rotation is based on eligible players
  let dealerPosition: number | undefined;
  let sbPosition: number | undefined;
  let bbPosition: number | undefined;
  const activeCount = active.length;

  if (activeCount > 0) {
    const sbIndexInActive = handIndex % activeCount;
    // In Heads-up (2 players), Dealer is SB. In 3+ players, Dealer is before SB.
    const dealerIndexInActive = activeCount === 2 
      ? sbIndexInActive 
      : (sbIndexInActive - 1 + activeCount) % activeCount;
      
    const dealerPlayer = active[dealerIndexInActive];
    if (dealerPlayer) {
      const dealerId = toNumber(dealerPlayer.agent_id ?? dealerPlayer.id ?? dealerPlayer.sid);
      dealerPosition = seatOrder.findIndex(p => toNumber(p.agent_id ?? p.id ?? p.sid) === dealerId);
    }

    // Determine SB and BB positions relative to active players
    const sbPlayer = active[sbIndexInActive];
    if (sbPlayer) {
      const sbId = toNumber(sbPlayer.agent_id ?? sbPlayer.id ?? sbPlayer.sid);
      sbPosition = seatOrder.findIndex(p => toNumber(p.agent_id ?? p.id ?? p.sid) === sbId);
    }

    const bbIndexInActive = (sbIndexInActive + 1) % activeCount;
    const bbPlayer = active[bbIndexInActive];
    if (bbPlayer) {
      const bbId = toNumber(bbPlayer.agent_id ?? bbPlayer.id ?? bbPlayer.sid);
      bbPosition = seatOrder.findIndex(p => toNumber(p.agent_id ?? p.id ?? p.sid) === bbId);
    }
  }

  if (dealerPosition === -1 || dealerPosition === undefined) {
    // Fallback if something goes wrong
    dealerPosition = seatOrder.length > 0 ? handIndex % seatOrder.length : undefined;
  }

  const timers = gameState.timers && typeof gameState.timers === 'object' ? gameState.timers as Record<string, number> : undefined;
  const winnerSource = inner.winner_ids ?? gameState.winner_ids;
  const winnerIds = Array.isArray(winnerSource)
    ? winnerSource.map((id) => toString(id))
    : (inner.winner_id ?? gameState.winner_id ? [toString(inner.winner_id ?? gameState.winner_id)] : undefined);

  return {
    game_id: toString(gameState.game_id ?? ''),
    phase: toString(gameState.phase ?? inner.phase ?? 'lobby'),
    pot,
    current_bet: currentBet,
    community_cards: board,
    players: mappedPlayers,
    dealer_position: dealerPosition,
    sb_position: sbPosition,
    bb_position: bbPosition,
    current_player: actorId !== undefined && actorId !== null ? toString(actorId) : undefined,
    hand_number: handIndex,
    hand_actions: handActions,
    small_blind: smallBlind,
    big_blind: bigBlind,
    winners: winnerIds,
    timers,
  };
};

export const normalizeWerewolfPhase = (phase: string): string => {
  const nightPhases = new Set(['wolf_chat', 'wolf_kill', 'witch', 'seer', 'guard']);
  if (nightPhases.has(phase)) return 'night';
  if (phase === 'day_debate') return 'day_discussion';
  if (phase === 'day_vote') return 'day_voting';
  return phase;
};

export const mapWerewolfRoomState = (roomState: Record<string, unknown>): WerewolfGameState | null => {
  const gameState = (roomState?.game_state ?? roomState?.gameState ?? roomState) as Record<string, unknown>;
  if (!gameState) return null;
  const playersRaw = Array.isArray(gameState.players) ? gameState.players : [];
  const roles = (gameState.roles || {}) as Record<string | number, unknown>;
  const aliveRaw = (gameState.alive || []) as (string | number)[];
  const alive = new Set<number>(aliveRaw.map((id: string | number) => toNumber(id)));
  const votesRaw = gameState.votes && typeof gameState.votes === 'object' ? gameState.votes : {};
  const votes: Record<string, string> = {};
  Object.entries(votesRaw).forEach(([voter, target]) => {
    votes[toString(voter)] = toString(target);
  });
  const voteCountsRaw = gameState.vote_counts && typeof gameState.vote_counts === 'object' ? gameState.vote_counts : {};
  const voteCounts: Record<string, number> = {};
  Object.entries(voteCountsRaw).forEach(([target, count]) => {
    voteCounts[toString(target)] = toNumber(count, 0);
  });
  const eliminated = Array.isArray(gameState.eliminated)
    ? gameState.eliminated.map((id: number | string) => toString(id))
    : undefined;
  const eliminatedLastNight = Array.isArray(gameState.eliminated_last_night)
    ? gameState.eliminated_last_night.map((id: number | string) => toString(id))
    : (gameState.eliminated_last_night ? [toString(gameState.eliminated_last_night)] : undefined);
  const offlineDeaths = Array.isArray(gameState.offline_deaths)
    ? gameState.offline_deaths.map((id: number | string) => toString(id))
    : undefined;
  const phaseReason = toString(gameState.reason ?? gameState.phase_reason ?? '', '');
  const phaseForced = Boolean(gameState.phase_forced ?? false);
  const seatOrder = [...playersRaw].sort((a, b) => toNumber(a.seat) - toNumber(b.seat));

  const mappedPlayers: WerewolfPlayer[] = seatOrder.map((player) => {
    const id = toNumber(player.agent_id ?? player.id ?? player.sid);
    const nickname = player.agent_name ?? player.nickname ?? `agent_${id}`;
    const roleInfo = roles[id] ?? roles[toString(id)];
    let role: WerewolfPlayer['role'];
    if (roleInfo) {
      if (typeof roleInfo === 'string') {
        role = roleInfo;
      } else if (typeof roleInfo === 'object') {
        const roleObj = roleInfo as Record<string, unknown>;
        if (roleObj.label) {
          role = roleObj.label as string;
        } else if (roleObj.role) {
          role = String(roleObj.role);
        }
      }
    }
    return {
      sid: toString(id),
      nickname,
      role,
      is_alive: alive.has(id),
      status: alive.has(id) ? 'alive' : 'dead',
    };
  });

  const phaseRaw = toString(gameState.phase ?? 'lobby');
  const phase = normalizeWerewolfPhase(phaseRaw);
  const winnerIds = Array.isArray(gameState.winner_ids)
    ? gameState.winner_ids.map((id: number | string) => toString(id))
    : (gameState.winner ? [toString(gameState.winner)] : undefined);
  const timers = gameState.timers && typeof gameState.timers === 'object' ? gameState.timers as Record<string, number> : undefined;

  return {
    game_id: toString(gameState.game_id ?? ''),
    phase,
    day_count: toNumber(gameState.day ?? 0),
    players: mappedPlayers,
    current_speaker: gameState.current_speaker !== undefined && gameState.current_speaker !== null ? toString(gameState.current_speaker) : undefined,
    winners: winnerIds,
    chat_messages: Array.isArray(gameState.chat_messages) ? gameState.chat_messages : [],
    timers,
    votes,
    vote_counts: Object.keys(voteCounts).length ? voteCounts : undefined,
    eliminated,
    eliminated_last_night: eliminatedLastNight,
    offline_deaths: offlineDeaths,
    phase_reason: phaseReason || undefined,
    phase_forced: phaseForced || undefined,
  };
};

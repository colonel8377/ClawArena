import type { TexasGameState, WerewolfGameState, SpectatorPlayer, WerewolfPlayer } from '@/store/types';

const toNumber = (value: unknown, fallback = 0): number => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

const toString = (value: unknown, fallback = ''): string => {
  if (value === null || value === undefined) return fallback;
  return String(value);
};

export const unwrapSocketPayload = <T = any>(payload: any): T => {
  if (payload && typeof payload === 'object' && 'ok' in payload && 'data' in payload) {
    return payload.data as T;
  }
  return payload as T;
};

export const mapTexasRoomState = (roomState: any): TexasGameState | null => {
  const gameState = roomState?.game_state ?? roomState?.gameState ?? roomState;
  if (!gameState) return null;
  const inner = gameState.state || {};
  const smallBlind = toNumber(inner.small_blind ?? gameState.small_blind ?? 1, 1);
  const bigBlind = toNumber(inner.big_blind ?? gameState.big_blind ?? 2, 2);
  const playersRaw = Array.isArray(gameState.players) ? gameState.players : [];
  const stacks = inner.stacks || gameState.stacks || {};
  const bets = inner.bets || {};
  const statuses = inner.statuses || {};
  const leftPlayers = new Set<number>((gameState.left_players || inner.left_players || []).map((id: any) => toNumber(id)));
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
  const holeMap: Record<number, string[]> = {};
  holeCards.forEach((cards: any, idx: number) => {
    const player = handOrder[idx];
    if (!player) return;
    const id = toNumber(player.agent_id ?? player.id ?? player.sid);
    holeMap[id] = Array.isArray(cards) ? cards.map((c) => toString(c)) : [];
  });

  const mappedPlayers: SpectatorPlayer[] = seatOrder.map((player) => {
    const id = toNumber(player.agent_id ?? player.id ?? player.sid);
    const nickname = player.agent_name ?? player.nickname ?? `agent_${id}`;
    const chips = toNumber(stacks[id] ?? player.chips ?? 0);
    const isActive = Boolean(statuses[id]);
    const status = isActive ? 'active' : (chips > 0 ? 'folded' : 'sitout');
    const currentBet = toNumber(bets[id] ?? 0);
    return {
      sid: toString(id),
      nickname,
      chips,
      status,
      hole_cards: holeMap[id],
      current_bet: currentBet,
    };
  });

  const pot = toNumber(inner.pot ?? 0);
  const board = Array.isArray(inner.board) ? inner.board.map((c: any) => toString(c)) : [];
  const currentBet = Math.max(0, ...Object.values(bets).map((value) => toNumber(value)));
  const actorId = inner.actor_id ?? inner.actorId;
  const dealerPosition = seatOrder.length > 0 ? handIndex % seatOrder.length : undefined;
  const timers = gameState.timers && typeof gameState.timers === 'object' ? gameState.timers : undefined;

  return {
    game_id: toString(gameState.game_id ?? ''),
    phase: toString(gameState.phase ?? inner.phase ?? 'lobby'),
    pot,
    current_bet: currentBet,
    community_cards: board,
    players: mappedPlayers,
    dealer_position: dealerPosition,
    current_player: actorId !== undefined && actorId !== null ? toString(actorId) : undefined,
    hand_number: handIndex,
    small_blind: smallBlind,
    big_blind: bigBlind,
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

export const mapWerewolfRoomState = (roomState: any): WerewolfGameState | null => {
  const gameState = roomState?.game_state ?? roomState?.gameState ?? roomState;
  if (!gameState) return null;
  const playersRaw = Array.isArray(gameState.players) ? gameState.players : [];
  const roles = gameState.roles || {};
  const alive = new Set<number>((gameState.alive || []).map((id: any) => toNumber(id)));
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
    ? gameState.eliminated.map((id: any) => toString(id))
    : undefined;
  const eliminatedLastNight = Array.isArray(gameState.eliminated_last_night)
    ? gameState.eliminated_last_night.map((id: any) => toString(id))
    : (gameState.eliminated_last_night ? [toString(gameState.eliminated_last_night)] : undefined);
  const offlineDeaths = Array.isArray(gameState.offline_deaths)
    ? gameState.offline_deaths.map((id: any) => toString(id))
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
      } else if (roleInfo.label) {
        role = roleInfo.label;
      } else if (roleInfo.role) {
        role = String(roleInfo.role);
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
    ? gameState.winner_ids.map((id: any) => toString(id))
    : (gameState.winner ? [toString(gameState.winner)] : undefined);
  const timers = gameState.timers && typeof gameState.timers === 'object' ? gameState.timers : undefined;

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

'use client';

import React from 'react';
import { useParams } from 'next/navigation';
import { useSpectatorSocket } from '@/hooks/useSpectatorSocket';
import { useWerewolfStore } from '@/store/werewolfStore';
import { ChatMessage, WerewolfPlayer } from '@/store/types';
import { useUiMode } from '@/components/UiModeProvider';
import DayNightCycle from '@/components/werewolf/DayNightCycle';
import WerewolfTableStage, { WEREWOLF_STAGE_HEIGHT, WEREWOLF_STAGE_WIDTH } from '@/components/werewolf/WerewolfTableStage';
import { mapWerewolfRoomState, normalizeWerewolfPhase } from '@/lib/stateAdapters';
import { fetchRoomChatHistory, fetchRoomEventHistory } from '@/lib/roomsApi';

const hashString = (value: string) => {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
};

const getPlayerHue = (key: string) => (hashString(key) * 47) % 360;

const getRoleName = (role?: WerewolfPlayer['role']) => {
  if (!role) return undefined;
  if (typeof role === 'string') return role;
  return role.role;
};

const BACKFILL_INTERVAL_MS = 5000;
const WEREWOLF_EVENT_TYPES = [
  'ww:night:action',
  'ww:day:vote',
  'ww:chat:day',
  'ww:phase:change',
];

type ActionFeedItem = {
  id: string;
  ts_ms: number;
  message: string;
  actorLabel?: string;
  content?: string;
  icon?: string;
  phase?: string;
};

const parseStreamId = (value?: string | null) => {
  if (!value) return null;
  const [msRaw, seqRaw] = String(value).split('-');
  const ms = Number(msRaw);
  const seq = Number(seqRaw ?? 0);
  if (!Number.isFinite(ms)) return null;
  return { ms, seq: Number.isFinite(seq) ? seq : 0 };
};

const compareStreamId = (a?: string | null, b?: string | null) => {
  const left = parseStreamId(a);
  const right = parseStreamId(b);
  if (!left && !right) return 0;
  if (!left) return -1;
  if (!right) return 1;
  if (left.ms !== right.ms) return left.ms - right.ms;
  return left.seq - right.seq;
};

const getEventTimeMs = (item?: { ts_ms?: number; timestamp?: string | null }) => {
  if (!item) return 0;
  if (Number.isFinite(item.ts_ms)) return Number(item.ts_ms);
  if (item.timestamp) return new Date(item.timestamp).getTime();
  return 0;
};

type JsonRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is JsonRecord =>
  Boolean(value) && typeof value === 'object';

const getRecord = (value: unknown): JsonRecord | null => (isRecord(value) ? value : null);

const toDedupeId = (value: unknown): string | number | undefined => {
  if (typeof value === 'string' || typeof value === 'number') return value;
  return undefined;
};

const toStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.map((entry) => String(entry)) : [];

const resolveEnvelopePayload = (rawEvent: unknown) => {
  const record = getRecord(rawEvent);
  const envelope = record && typeof record['event_type'] === 'string' ? record : null;
  const inner = getRecord(envelope ? envelope['payload'] : record?.['payload']) ?? record;
  const payload = getRecord(inner?.['payload']) ?? {};
  return { envelope, inner, payload };
};

const compareByEventTimeDesc = (
  a?: { ts_ms?: number; timestamp?: string | null; event_id?: string; id?: string },
  b?: { ts_ms?: number; timestamp?: string | null; event_id?: string; id?: string }
) => {
  const delta = getEventTimeMs(b) - getEventTimeMs(a);
  if (delta !== 0) return delta;
  const streamDelta = compareStreamId(a?.event_id ?? a?.id ?? null, b?.event_id ?? b?.id ?? null);
  if (streamDelta !== 0) return -streamDelta;
  return 0;
};

const resolveDedupeId = (...candidates: Array<string | number | null | undefined>) => {
  for (const candidate of candidates) {
    if (candidate === null || candidate === undefined) continue;
    const value = String(candidate);
    if (value) return value;
  }
  return null;
};

const formatActionActorLabel = (label?: string | null) => {
  if (!label) return label;
  return label.replace('WEREWOLF', 'WOLF');
};

const splitSystemMessage = (content: string) => {
  const text = String(content || '').trim();
  if (!text) return { icon: 'ℹ️', text: '' };
  const icons = ['🕒', '🏆', '🗳️', '☠️', '⚠️', '⏲️', '📣', '✅', '❌', '💬'];
  for (const icon of icons) {
    if (text.startsWith(`${icon} `)) {
      return { icon, text: text.slice(icon.length + 1).trim() };
    }
    if (text.startsWith(icon)) {
      return { icon, text: text.slice(icon.length).trim() };
    }
  }
  const lower = text.toLowerCase();
  if (lower.includes('phase')) return { icon: '🕒', text };
  if (lower.includes('winner')) return { icon: '🏆', text };
  if (lower.includes('vote') || lower.includes('elimination')) return { icon: '🗳️', text };
  if (lower.includes('eliminated') || lower.includes('killed') || lower.includes('death')) return { icon: '☠️', text };
  if (lower.includes('timeout') || lower.includes('timed out')) return { icon: '⏲️', text };
  if (lower.includes('offline')) return { icon: '⚠️', text };
  if (lower.includes('announce')) return { icon: '📣', text };
  return { icon: 'ℹ️', text };
};

export default function WerewolfGamePage() {
  const { gameId: roomId } = useParams() as { gameId: string };
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';
  const stageContainerRef = React.useRef<HTMLDivElement | null>(null);
  const [stageSize, setStageSize] = React.useState({ width: 0, height: 0 });
  
  const {
    gameState,
    setGameState,
    setConnected,
  } = useWerewolfStore();

  const [loadStatus, setLoadStatus] = React.useState<'loading' | 'ready' | 'ended' | 'error'>('loading');
  React.useEffect(() => {
    const node = stageContainerRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const update = () => {
      const rect = node.getBoundingClientRect();
      setStageSize({ width: rect.width, height: rect.height });
    };
    const observer = new ResizeObserver(update);
    observer.observe(node);
    update();
    return () => observer.disconnect();
  }, []);

  // Derived state for current speaker based on recent chat messages
  const [activeMessage, setActiveMessage] = React.useState<{ sid: string; content: string } | undefined>(undefined);
  
  // Local system logs for phase changes and deaths
  const [systemLogs, setSystemLogs] = React.useState<ChatMessage[]>([]);
  const prevPhase = React.useRef<string | undefined>(undefined);
  const prevPlayers = React.useRef<WerewolfPlayer[] | undefined>(undefined);
  const prevEliminated = React.useRef<string | undefined>(undefined);
  const prevDayEliminated = React.useRef<string | undefined>(undefined);
  const prevVoteCounts = React.useRef<string | undefined>(undefined);
  const prevOfflineDeaths = React.useRef<string | undefined>(undefined);
  const prevWinners = React.useRef<string[] | undefined>(undefined);
  const prevPhaseNormalized = React.useRef<string | undefined>(undefined);
  const loggedDeathSids = React.useRef<Set<string>>(new Set());
  const systemLogKeys = React.useRef<Set<string>>(new Set());
  const [phaseRemainingMs, setPhaseRemainingMs] = React.useState<number | null>(null);
  const pendingHistory = React.useRef<ChatMessage[] | null>(null);
  const chatSeenRef = React.useRef<Set<string>>(new Set());
  const actionSeenRef = React.useRef<Set<string>>(new Set());
  const lastEventIdRef = React.useRef<string | null>(null);
  const lastChatIdRef = React.useRef<string | null>(null);
  const backfillEventsRef = React.useRef(false);
  const backfillChatRef = React.useRef(false);
  const initialEventsRef = React.useRef(false);
  const initialChatRef = React.useRef(false);
  const [actionFeed, setActionFeed] = React.useState<ActionFeedItem[]>([]);
  const [victoryBanner, setVictoryBanner] = React.useState<{
    id: string;
    message: string;
    winners: string[];
    reason?: string;
  } | null>(null);
  const nightActionRef = React.useRef<{
    wolfKill?: { actorId?: string; targetId?: string };
    witchSave?: { actorId?: string };
    witchPoison?: { actorId?: string; targetId?: string };
    guard?: { actorId?: string; targetId?: string };
    seer?: { actorId?: string; targetId?: string };
  }>({});
  const pushAction = React.useCallback((item: ActionFeedItem) => {
    if (!item || !item.id) return;
    if (actionSeenRef.current.has(item.id)) return;
    actionSeenRef.current.add(item.id);
    setActionFeed((prev) => [...prev, item].slice(-20));
  }, []);

  const trackLastEventId = React.useCallback((candidate?: string | null) => {
    if (!candidate) return;
    const next = String(candidate);
    const current = lastEventIdRef.current;
    if (!current || compareStreamId(next, current) > 0) {
      lastEventIdRef.current = next;
    }
  }, []);

  const trackLastChatId = React.useCallback((candidate?: string | null) => {
    if (!candidate) return;
    const next = String(candidate);
    const current = lastChatIdRef.current;
    if (!current || compareStreamId(next, current) > 0) {
      lastChatIdRef.current = next;
    }
  }, []);

  const resolveDisplayName = React.useCallback((sid?: string | null, fallback?: string) => {
    if (!sid) return fallback ?? 'UNKNOWN';
    const state = useWerewolfStore.getState().gameState;
    if (!state || !Array.isArray(state.players)) return fallback ?? `PLAYER ${sid}`;
    const idx = state.players.findIndex((p) => p.sid === String(sid));
    if (idx < 0) return fallback ?? `PLAYER ${sid}`;
    const roleName = getRoleName(state.players[idx].role);
    const label = roleName ? roleName.toUpperCase() : 'PLAYER';
    return `${label} ${idx + 1}`;
  }, []);

  const resolveDisplayNameFromValue = React.useCallback(
    (value?: string | number | null, fallback?: string) => {
      if (value === null || value === undefined) return fallback ?? 'UNKNOWN';
      const id = String(value);
      return resolveDisplayName(id, fallback ?? id);
    },
    [resolveDisplayName]
  );

  const resolveWinnerLabel = React.useCallback((value?: string | number | null) => {
    if (value === null || value === undefined) return 'UNKNOWN';
    const raw = String(value);
    const isNumeric = /^[0-9]+$/.test(raw);
    if (!isNumeric) {
      const lower = raw.toLowerCase();
      if (lower.includes('wolf')) return '🐺 WEREWOLVES';
      if (lower.includes('villager') || lower.includes('human')) return '🧑 VILLAGERS';
      if (lower.includes('no_contest') || lower.includes('no contest')) return '⚠️ NO CONTEST';
      if (lower.includes('seer')) return '🔮 SEER';
      if (lower.includes('witch')) return '🧪 WITCH';
      if (lower.includes('hunter')) return '🔫 HUNTER';
      if (lower.includes('guard')) return '🛡️ GUARD';
      if (lower.includes('agent')) return '🤖 AGENTS';
      return raw.toUpperCase();
    }
    return resolveDisplayNameFromValue(raw);
  }, [resolveDisplayNameFromValue]);

  const resolveEndReasonLabel = React.useCallback((reason?: string | null) => {
    if (!reason) return null;
    const lower = String(reason).toLowerCase();
    if (lower.includes('all_offline')) return 'ENDED EARLY · ALL OFFLINE';
    if (lower.includes('no_alive')) return 'ENDED · NO ALIVE';
    if (lower.includes('timeout')) return 'ENDED · TIMEOUT';
    if (lower.includes('leave')) return 'ENDED · PLAYER LEFT';
    return `ENDED · ${String(reason).toUpperCase()}`;
  }, []);

  const resolveChatPhase = React.useCallback(
    (
      input?: { phase?: string | null; channel?: string | null; is_wolf_chat?: boolean | null },
      fallbackPhase?: string | null
    ) => {
      if (input?.phase) return normalizeWerewolfPhase(String(input.phase));
      if (input?.is_wolf_chat || input?.channel === 'wolf') return 'night';
      if (fallbackPhase) return normalizeWerewolfPhase(String(fallbackPhase));
      return undefined;
    },
    []
  );


  const buildNightActionItem = React.useCallback((rawEvent: unknown): ActionFeedItem | null => {
    const { envelope, inner } = resolveEnvelopePayload(rawEvent);
    if (!inner) return null;
    const payload = getRecord(inner['payload']) ?? {};
    const actionType = Number(inner['action_type']);
    const actorRaw = inner['actor_id'];
    const actorId = actorRaw !== undefined && actorRaw !== null ? String(actorRaw) : undefined;
    const targetRaw = payload['target_id'];
    const targetId = targetRaw !== undefined && targetRaw !== null ? String(targetRaw) : undefined;
    const actorLabel = actorId ? resolveDisplayName(actorId) : undefined;
    const targetLabel = targetId ? resolveDisplayName(targetId) : undefined;
    let icon = '';
    let content = '';
    if (actionType === 4 && targetLabel) {
      nightActionRef.current.wolfKill = { actorId, targetId };
      icon = '🐺';
      content = `targeted ${targetLabel}`;
    } else if (actionType === 6) {
      nightActionRef.current.witchSave = { actorId };
      icon = '🧪';
      content = 'used antidote';
    } else if (actionType === 7 && targetLabel) {
      nightActionRef.current.witchPoison = { actorId, targetId };
      icon = '🧪';
      content = `poisoned ${targetLabel}`;
    } else if (actionType === 5 && targetLabel) {
      nightActionRef.current.seer = { actorId, targetId };
      icon = '🔮';
      content = `checked ${targetLabel}`;
    } else if (actionType === 3 && targetLabel) {
      nightActionRef.current.guard = { actorId, targetId };
      icon = '🛡️';
      content = `protected ${targetLabel}`;
    }
    if (!content) return null;
    const message = `${icon ? `${icon} ` : ''}${actorLabel ?? 'UNKNOWN'} ${content}`.trim();
    const id =
      resolveDedupeId(
        toDedupeId(envelope?.['action_id']),
        toDedupeId(inner['action_id']),
        toDedupeId(envelope?.['event_id']),
        toDedupeId(inner['event_id']),
        toDedupeId(envelope?.['id']),
        toDedupeId(inner['id'])
      ) ||
      `${actionType}-${actorId || 'na'}-${targetId || 'na'}-${inner['ts_ms'] ?? Date.now()}`;
    const ts_ms = Number(envelope?.['ts_ms'] ?? inner['ts_ms'] ?? Date.now());
    const rawPhase = inner['phase'] ?? envelope?.['phase'] ?? 'night';
    const phase = rawPhase ? normalizeWerewolfPhase(String(rawPhase)) : undefined;
    return {
      id: String(id),
      ts_ms,
      message,
      actorLabel,
      content,
      icon,
      phase
    };
  }, [resolveDisplayName]);

  const buildDayVoteActionItem = React.useCallback((rawEvent: unknown): ActionFeedItem | null => {
    const { envelope, inner } = resolveEnvelopePayload(rawEvent);
    if (!inner) return null;
    const actionType = Number(inner['action_type']);
    if (actionType !== 9) return null;
    const actorRaw = inner['actor_id'];
    const actorId = actorRaw !== undefined && actorRaw !== null ? String(actorRaw) : undefined;
    const payload = getRecord(inner['payload']) ?? {};
    const targetRaw = payload['target_id'];
    const targetId = targetRaw !== undefined && targetRaw !== null ? String(targetRaw) : undefined;
    if (!actorId || !targetId) return null;
    const actorLabel = resolveDisplayName(actorId);
    const targetLabel = resolveDisplayName(targetId);
    const message = `🗳️ ${actorLabel} voted ${targetLabel}`;
    const id =
      resolveDedupeId(
        toDedupeId(envelope?.['action_id']),
        toDedupeId(inner['action_id']),
        toDedupeId(envelope?.['event_id']),
        toDedupeId(inner['event_id']),
        toDedupeId(envelope?.['id']),
        toDedupeId(inner['id'])
      ) ||
      `vote-${actorId}-${targetId}-${inner['ts_ms'] ?? Date.now()}`;
    const ts_ms = Number(envelope?.['ts_ms'] ?? inner['ts_ms'] ?? Date.now());
    const rawPhase = inner['phase'] ?? envelope?.['phase'] ?? 'day';
    const phase = rawPhase ? normalizeWerewolfPhase(String(rawPhase)) : undefined;
    return {
      id: String(id),
      ts_ms,
      message,
      actorLabel,
      content: `vote ${targetLabel}`,
      icon: '🗳️',
      phase
    };
  }, [resolveDisplayName]);

  const buildDaySpeakActionItem = React.useCallback((rawEvent: unknown): ActionFeedItem | null => {
    const { envelope, inner } = resolveEnvelopePayload(rawEvent);
    if (!inner) return null;
    const actionType = Number(inner['action_type']);
    if (actionType !== 8) return null;
    const actorRaw = inner['actor_id'];
    const actorId = actorRaw !== undefined && actorRaw !== null ? String(actorRaw) : undefined;
    const payload = getRecord(inner['payload']) ?? {};
    const content = String(payload['content'] ?? payload['msg'] ?? '').trim();
    const meta = getRecord(payload['meta']) ?? {};
    const isTimeout = meta['reason'] === 'timeout' || meta['auto'] === true;
    if (!actorId) return null;
    if (!content && !isTimeout) return null;
    const actorLabel = resolveDisplayName(actorId);
    const message = content
      ? `🗣️ ${actorLabel}: ${content}`
      : `⏲️ ${actorLabel} timed out (no speech)`;
    const id =
      resolveDedupeId(
        toDedupeId(envelope?.['action_id']),
        toDedupeId(inner['action_id']),
        toDedupeId(envelope?.['event_id']),
        toDedupeId(inner['event_id']),
        toDedupeId(envelope?.['id']),
        toDedupeId(inner['id'])
      ) ||
      `speak-${actorId}-${inner['ts_ms'] ?? Date.now()}`;
    const ts_ms = Number(envelope?.['ts_ms'] ?? inner['ts_ms'] ?? Date.now());
    const rawPhase = inner['phase'] ?? envelope?.['phase'] ?? 'day';
    const phase = rawPhase ? normalizeWerewolfPhase(String(rawPhase)) : undefined;
    return {
      id: String(id),
      ts_ms,
      message,
      actorLabel,
      content: content ? content : 'timed out',
      icon: content ? '🗣️' : '⏲️',
      phase
    };
  }, [resolveDisplayName]);

  const buildActionFeedItem = React.useCallback((rawEvent: unknown): ActionFeedItem | null => {
    const record = getRecord(rawEvent);
    const eventType = typeof record?.['event_type'] === 'string' ? record['event_type'] : undefined;
    if (eventType === 'ww:night:action') return buildNightActionItem(rawEvent);
    if (eventType === 'ww:day:vote') return buildDayVoteActionItem(rawEvent);
    if (eventType === 'ww:chat:day') return buildDaySpeakActionItem(rawEvent);
    return null;
  }, [buildDaySpeakActionItem, buildDayVoteActionItem, buildNightActionItem]);

  const applyPhaseChange = React.useCallback((event: any) => {
    const inner = event?.payload ?? event;
    const payload = inner?.payload || {};
    const current = useWerewolfStore.getState().gameState;
    if (!current) return;
    const alive = Array.isArray(payload.alive) ? payload.alive.map((id: any) => String(id)) : [];
    const voteCountsRaw = payload.vote_counts && typeof payload.vote_counts === 'object' ? payload.vote_counts : undefined;
    const voteCounts: Record<string, number> | undefined = voteCountsRaw
      ? Object.entries(voteCountsRaw).reduce<Record<string, number>>((acc, [target, count]) => {
          acc[String(target)] = Number(count) || 0;
          return acc;
        }, {})
      : undefined;
    const eliminated = Array.isArray(payload.eliminated)
      ? payload.eliminated.map((id: any) => String(id))
      : undefined;
    const offlineDeaths = Array.isArray(payload.offline_deaths)
      ? payload.offline_deaths.map((id: any) => String(id))
      : undefined;
    const phaseReason = payload.reason ?? payload?.meta?.reason ?? undefined;
    const updatedPlayers = current.players.map((player) => {
      if (!alive.length) return player;
      return {
        ...player,
        is_alive: alive.includes(player.sid),
      };
    });
    const phase = payload.phase ? normalizeWerewolfPhase(String(payload.phase)) : current.phase;
    const nextState = {
      ...current,
      phase,
      day_count: payload.day ?? current.day_count,
      current_speaker: payload.current_speaker ? String(payload.current_speaker) : current.current_speaker,
      players: updatedPlayers,
      winners: payload.winner ? [String(payload.winner)] : current.winners,
      timers: payload.timers ?? current.timers,
      vote_counts: voteCounts ?? (payload.phase ? undefined : current.vote_counts),
      eliminated: eliminated ?? (payload.phase ? undefined : current.eliminated),
      offline_deaths: offlineDeaths ?? (payload.phase ? undefined : current.offline_deaths),
      phase_reason: phaseReason ?? (payload.phase ? undefined : current.phase_reason),
    };
    setGameState(nextState);
  }, [setGameState]);

  const applyVoteUpdate = React.useCallback((event: any) => {
    const current = useWerewolfStore.getState().gameState;
    if (!current) return;
    const inner = event?.payload ?? event;
    const actorId = inner?.actor_id;
    const targetId = inner?.payload?.target_id;
    if (!actorId || !targetId) return;
    const nextVotes = { ...(current.votes || {}) };
    nextVotes[String(actorId)] = String(targetId);
    setGameState({ ...current, votes: nextVotes });
  }, [setGameState]);



  React.useEffect(() => {
    if (!gameState) return;
    setLoadStatus('ready');

    const newLogs: ChatMessage[] = [];
    const nowMs = Date.now();
    const now = new Date(nowMs).toISOString();
    const normalizedPhase = gameState.phase ? normalizeWerewolfPhase(gameState.phase) : undefined;
    if (normalizedPhase === 'night' && prevPhaseNormalized.current !== 'night') {
      nightActionRef.current = {};
    }
    prevPhaseNormalized.current = normalizedPhase;
    const addSystemLog = (key: string, message: string, sid: string, toAction = false) => {
      if (systemLogKeys.current.has(key)) return;
      systemLogKeys.current.add(key);
      newLogs.push({
        nickname: 'SYSTEM',
        message,
        timestamp: now,
        ts_ms: nowMs,
        sid,
        phase: normalizedPhase,
        isSystem: true
      });
      if (toAction) {
        pushAction({
          id: `system:${key}`,
          ts_ms: nowMs,
          message,
          content: message,
          actorLabel: 'TOWN',
          icon: '🏘️',
          phase: normalizedPhase
        });
      }
    };

    const emitResultAction = (
      key: string,
      actorLabel: string,
      verb: string,
      targetLabel: string,
      icon: string,
      phaseOverride?: string
    ) => {
      pushAction({
        id: key,
        ts_ms: nowMs,
        message: `${icon} ${actorLabel} ${verb} ${targetLabel}`,
        actorLabel,
        content: `${verb} ${targetLabel}`,
        icon,
        phase: phaseOverride ?? normalizedPhase
      });
    };

    prevPhase.current = gameState.phase;

    const nightActions = nightActionRef.current;
    const wolfTarget = nightActions.wolfKill?.targetId;
    const wolfActor = nightActions.wolfKill?.actorId;
    const witchPoisonTarget = nightActions.witchPoison?.targetId;
    const witchPoisonActor = nightActions.witchPoison?.actorId;
    const witchSaveActor = nightActions.witchSave?.actorId;
    const resolveActor = (actorId?: string, fallback?: string) => {
      if (actorId) return formatActionActorLabel(resolveDisplayName(actorId)) || resolveDisplayName(actorId);
      return fallback || 'TOWN';
    };
    const nightDeathIds = new Set<string>();

    // Check Deaths — prefer structured deaths array from backend
    if (gameState.deaths && gameState.deaths.length > 0) {
      for (const death of gameState.deaths) {
        if (loggedDeathSids.current.has(death.sid)) continue;
        loggedDeathSids.current.add(death.sid);
        const deathId = String(death.sid);
        nightDeathIds.add(deathId);
        const deathName = resolveDisplayNameFromValue(death.sid, death.nickname);
        const key = `result:death:${deathId}:${death.cause || 'unknown'}`;
        if (death.cause === 'vote') {
          emitResultAction(key, 'TOWN', 'eliminate', deathName, '🗳️');
          continue;
        }
        if (death.cause === 'poison' || (witchPoisonTarget && String(witchPoisonTarget) === deathId)) {
          const actor = resolveActor(witchPoisonActor, 'WITCH');
          emitResultAction(key, actor, 'poison', deathName, '🧪');
          continue;
        }
        if (death.cause === 'wolf_kill' || (wolfTarget && String(wolfTarget) === deathId)) {
          const actor = resolveActor(wolfActor, 'WOLF');
          emitResultAction(key, actor, 'kill', deathName, '🐺');
          continue;
        }
        if (death.cause === 'hunter_shot') {
          emitResultAction(key, 'HUNTER', 'shot', deathName, '🔫');
          continue;
        }
        emitResultAction(key, 'TOWN', 'eliminate', deathName, '🗳️');
      }
    }

    // Fallback: detect deaths via player diff (for backends that don't send deaths array)
    if (prevPlayers.current) {
       gameState.players.forEach((p) => {
         if (loggedDeathSids.current.has(p.sid)) return;
         const oldP = prevPlayers.current?.find((op) => op.sid === p.sid);
         if (oldP && oldP.is_alive && !p.is_alive) {
            loggedDeathSids.current.add(p.sid);
            nightDeathIds.add(String(p.sid));
            const deathName = resolveDisplayNameFromValue(p.sid, p.nickname);
            const key = `result:death:diff:${p.sid}`;
            if (wolfTarget && String(wolfTarget) === String(p.sid)) {
              const actor = resolveActor(wolfActor, 'WOLF');
              emitResultAction(key, actor, 'kill', deathName, '🐺');
            } else {
              emitResultAction(key, 'TOWN', 'eliminate', deathName, '🗳️');
            }
         }
       });
    }
    prevPlayers.current = gameState.players;

    if (gameState.eliminated_last_night && gameState.eliminated_last_night.length > 0) {
      const key = gameState.eliminated_last_night.join(',');
      if (key !== prevEliminated.current) {
        gameState.eliminated_last_night.forEach((id) => {
          const sid = String(id);
          if (loggedDeathSids.current.has(sid)) return;
          loggedDeathSids.current.add(sid);
          nightDeathIds.add(sid);
          const targetLabel = resolveDisplayNameFromValue(sid);
          if (witchPoisonTarget && String(witchPoisonTarget) === sid) {
            const actor = resolveActor(witchPoisonActor, 'WITCH');
            emitResultAction(`result:night:poison:${sid}:${key}`, actor, 'poison', targetLabel, '🧪');
            return;
          }
          const actor = resolveActor(wolfActor, 'WOLF');
          emitResultAction(`result:night:kill:${sid}:${key}`, actor, 'kill', targetLabel, '🐺');
        });
        prevEliminated.current = key;
      }
    }

    if (wolfTarget && !nightDeathIds.has(String(wolfTarget)) && witchSaveActor) {
      const targetLabel = resolveDisplayNameFromValue(wolfTarget);
      const actor = resolveActor(witchSaveActor, 'WITCH');
      emitResultAction(
        `result:night:save:${wolfTarget}:${gameState.day_count ?? 0}`,
        actor,
        'save',
        targetLabel,
        '🧪'
      );
    }

    if (gameState.offline_deaths && gameState.offline_deaths.length > 0) {
      const key = gameState.offline_deaths.join(',');
      if (key !== prevOfflineDeaths.current) {
        gameState.offline_deaths.forEach((sid) => loggedDeathSids.current.add(sid));
        gameState.offline_deaths.forEach((sid) => {
          const targetLabel = resolveDisplayNameFromValue(sid);
          emitResultAction(
            `result:offline:${sid}:${key}`,
            'TOWN',
            'offline remove',
            targetLabel,
            '⚠️'
          );
        });
        prevOfflineDeaths.current = key;
      }
    }

    if (gameState.eliminated && gameState.eliminated.length > 0) {
      const key = gameState.eliminated.join(',');
      if (key !== prevDayEliminated.current) {
        gameState.eliminated.forEach((sid) => loggedDeathSids.current.add(sid));
        gameState.eliminated.forEach((sid) => {
          const targetLabel = resolveDisplayNameFromValue(sid);
          emitResultAction(
            `result:eliminate:${sid}:${key}`,
            'TOWN',
            'eliminate',
            targetLabel,
            '🗳️'
          );
        });
        prevDayEliminated.current = key;
      }
    }

    if (gameState.vote_counts && Object.keys(gameState.vote_counts).length > 0) {
      const entries = Object.entries(gameState.vote_counts)
        .map(([target, count]) => ({ target, count: Number(count) || 0 }))
        .sort((a, b) => b.count - a.count);
      const key = entries.map((entry) => `${entry.target}:${entry.count}`).join('|');
      if (key && key !== prevVoteCounts.current) {
        const summary = entries
          .map((entry) => `${resolveDisplayNameFromValue(entry.target)}=${entry.count}`)
          .join(', ');
        addSystemLog(`votes:${key}`, `🗳️ Votes: ${summary}`, 'system-default', true);
        if (!gameState.eliminated || gameState.eliminated.length === 0) {
          const reasonText = gameState.phase_reason ? ` (reason: ${gameState.phase_reason})` : '';
          if (reasonText) {
            addSystemLog(`no_elim:${key}:${gameState.phase_reason || ''}`, `🗳️ No elimination${reasonText}`, 'system-default', true);
          }
        }
        prevVoteCounts.current = key;
      }
    }

    if (gameState.winners && gameState.winners.length > 0) {
      const winnersKey = gameState.winners.join('|');
      const prevKey = prevWinners.current?.join('|');
      if (winnersKey !== prevKey) {
        const winnerNames = gameState.winners
          .map((id) => resolveWinnerLabel(id))
          .join(', ');
        addSystemLog(`winners:${winnersKey}`, `🏆 Winners: ${winnerNames}`, 'system-winners', true);
        prevWinners.current = [...gameState.winners];
      }
    }

    if (newLogs.length > 0) {
      setSystemLogs(prev => [...prev, ...newLogs]);
    }
  }, [gameState]);

  React.useEffect(() => {
    if (!gameState?.timers) {
      setPhaseRemainingMs(null);
      return;
    }
    const timers = gameState.timers;
    const speakerDeadline = Number(timers.speaker_deadline_ms ?? 0);
    const phaseDeadline = Number(timers.phase_deadline_ms ?? 0);
    const speakerRemaining = Number(timers.speaker_remaining_ms ?? 0);
    const phaseRemaining = Number(timers.phase_remaining_ms ?? 0);

    const compute = () => {
      if (Number.isFinite(speakerDeadline) && speakerDeadline > 0) {
        setPhaseRemainingMs(Math.max(0, speakerDeadline - Date.now()));
        return;
      }
      if (Number.isFinite(phaseDeadline) && phaseDeadline > 0) {
        setPhaseRemainingMs(Math.max(0, phaseDeadline - Date.now()));
        return;
      }
      if (Number.isFinite(speakerRemaining) && speakerRemaining > 0) {
        setPhaseRemainingMs(speakerRemaining);
        return;
      }
      if (Number.isFinite(phaseRemaining) && phaseRemaining > 0) {
        setPhaseRemainingMs(phaseRemaining);
        return;
      }
      setPhaseRemainingMs(null);
    };

    compute();
    const interval = setInterval(compute, 500);
    return () => clearInterval(interval);
  }, [gameState?.timers]);

  React.useEffect(() => {
    pendingHistory.current = null;
    chatSeenRef.current = new Set();
    actionSeenRef.current = new Set();
    lastEventIdRef.current = null;
    lastChatIdRef.current = null;
    backfillEventsRef.current = false;
    backfillChatRef.current = false;
    initialEventsRef.current = false;
    initialChatRef.current = false;
    setActionFeed([]);
    let mounted = true;
    const loadHistory = async () => {
      try {
        const history = await fetchRoomChatHistory(roomId, 100);
        if (!mounted) return;
        if (history.last_id) trackLastChatId(history.last_id);
        const fallbackPhase = useWerewolfStore.getState().gameState?.phase;
        const mapped = (history.items || []).reduce<ChatMessage[]>((acc, msg) => {
          const content = String(msg.content || '').trim();
          if (!content) return acc;
          acc.push({
            id: msg.id ? String(msg.id) : undefined,
            event_id: msg.event_id || undefined,
            action_id: msg.action_id || undefined,
            sid: msg.sender_id !== undefined && msg.sender_id !== null ? String(msg.sender_id) : undefined,
            nickname: msg.sender_name || `agent_${msg.sender_id ?? 'unknown'}`,
            message: content,
            timestamp: new Date(msg.ts_ms).toISOString(),
            ts_ms: msg.ts_ms,
            phase: resolveChatPhase({ phase: msg.phase, channel: msg.channel }, fallbackPhase),
            is_wolf_chat: msg.channel === 'wolf',
          });
          return acc;
        }, []);
        pendingHistory.current = mapped;
        const current = useWerewolfStore.getState().gameState;
        if (current) {
          const existing = current.chat_messages || [];
          const merged = [...mapped, ...existing];
          const seen = new Set<string>();
          const deduped = merged.filter((item) => {
            const key = item.action_id || item.event_id || item.id || `${item.sid || ''}|${item.timestamp || ''}|${item.message}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          });
          const normalized = deduped.slice(-200);
          chatSeenRef.current = new Set(
            normalized.map((item) => item.action_id || item.event_id || item.id || `${item.sid || ''}|${item.timestamp || ''}|${item.message}`)
          );
          setGameState({ ...current, chat_messages: normalized });
        }

        const actionHistory = await fetchRoomEventHistory(
          roomId,
          200,
          undefined,
          undefined,
          WEREWOLF_EVENT_TYPES,
          true
        );
        if (!mounted) return;
        if (actionHistory.last_id) trackLastEventId(actionHistory.last_id);
        const actionItems: ActionFeedItem[] = [];
        (actionHistory.items || []).forEach((item) => {
          if (item.event_type === 'ww:phase:change') {
            applyPhaseChange(item);
            return;
          }
          const feedItem = buildActionFeedItem(item);
          if (feedItem) actionItems.push(feedItem);
        });
        actionItems.sort((a, b) => a.ts_ms - b.ts_ms);
        actionSeenRef.current = new Set(actionItems.map((item) => item.id));
        setActionFeed(actionItems.slice(-20));
      } catch {
      }
    };
    loadHistory();
    return () => {
      mounted = false;
    };
  }, [applyPhaseChange, buildActionFeedItem, resolveChatPhase, roomId, setGameState, trackLastChatId, trackLastEventId]);

  const winnerLabels = React.useMemo(() => {
    if (!gameState?.winners || gameState.winners.length === 0) return [];
    return gameState.winners.map((id) => resolveWinnerLabel(id));
  }, [gameState?.winners, resolveWinnerLabel]);

  React.useEffect(() => {
    if (!gameState?.winners || gameState.winners.length === 0) {
      setVictoryBanner(null);
      return;
    }
    const labels = gameState.winners.map((id) => resolveWinnerLabel(id));
    const isNoContest = labels[0]?.includes('NO CONTEST');
    const message = isNoContest
      ? labels[0]
      : labels.length > 1
        ? `WINNERS: ${labels.join(' · ')}`
        : `WINNER: ${labels[0]}`;
    const reason = resolveEndReasonLabel(gameState.phase_reason);
    setVictoryBanner({ id: `${Date.now()}`, message, winners: labels, reason: reason || undefined });
  }, [gameState?.phase_reason, gameState?.winners, resolveEndReasonLabel, resolveWinnerLabel]);

  // Merge and sort messages
  const allMessages = React.useMemo(() => {
     const chats = gameState?.chat_messages || [];
     const combined = [...chats, ...systemLogs];
     return combined.sort((a, b) => {
        const tA = a.ts_ms ?? (a.timestamp ? new Date(a.timestamp).getTime() : 0);
        const tB = b.ts_ms ?? (b.timestamp ? new Date(b.timestamp).getTime() : 0);
        return tB - tA;
     });
  }, [gameState?.chat_messages, systemLogs]);

  const actionPanelItems = React.useMemo(() => {
    const items: Array<{
      id: string;
      ts_ms: number;
      content: string;
      actor?: string;
      icon?: string;
      tone: 'action' | 'system';
      phase?: string;
    }> = [];
    actionFeed.forEach((item) => {
      items.push({
        id: `action:${item.id}`,
        ts_ms: item.ts_ms,
        content: item.content || item.message,
        actor: item.actorLabel,
        icon: item.icon || '🎯',
        tone: 'action',
        phase: item.phase
      });
    });
    systemLogs.forEach((log, idx) => {
      const ts = log.ts_ms ?? (log.timestamp ? new Date(log.timestamp).getTime() : 0);
      items.push({
        id: `system:${log.event_id || log.id || idx}`,
        ts_ms: ts,
        content: log.message,
        actor: 'TOWN',
        icon: '🏘️',
        tone: 'system',
        phase: log.phase
      });
    });
    return items.sort((a, b) => b.ts_ms - a.ts_ms).slice(0, 60);
  }, [actionFeed, systemLogs]);

  const chatPanelItems = React.useMemo(
    () => allMessages.filter((item) => !item.isSystem),
    [allMessages]
  );

  const currentActionItem = React.useMemo<ActionFeedItem | null>(() => {
    let latest: ActionFeedItem | null = null;
    actionFeed.forEach((item) => {
      if (item.actorLabel === 'SYSTEM') return;
      if (item.icon === '🏘️') return;
      if (!latest || item.ts_ms > latest.ts_ms) {
        latest = item;
      }
    });
    return latest;
  }, [actionFeed]);

  const playerMeta = React.useMemo(() => {
    const map = new Map<string, { displayName: string; role?: string; color: string }>();
    (gameState?.players || []).forEach((p, idx) => {
      const roleName = getRoleName(p.role);
      const hue = getPlayerHue(p.sid || p.nickname);
      const label = roleName ? roleName.toUpperCase() : 'PLAYER';
      const displayName = `${label} ${idx + 1}`;
      map.set(p.sid, {
        displayName,
        role: roleName ? roleName.toUpperCase() : undefined,
        color: `hsl(${hue} 70% ${isAgent ? 65 : 40}%)`
      });
    });
    return map;
  }, [gameState?.players, isAgent]);

  React.useEffect(() => {
    if (!gameState?.chat_messages?.length) return;
    
    const lastMsg = gameState.chat_messages[gameState.chat_messages.length - 1];
    if (!lastMsg) return;

    // We can just set the speaker to the last message sender for a few seconds
    setActiveMessage({ sid: lastMsg.sid!, content: lastMsg.message });
    
    const timer = setTimeout(() => {
      setActiveMessage(undefined);
    }, 5000); // Highlight for 5 seconds

    return () => clearTimeout(timer);
  }, [gameState?.chat_messages]); // Re-run when chat messages update

  const appendChat = React.useCallback((message: ChatMessage) => {
    const current = useWerewolfStore.getState().gameState;
    if (!current) return;
    if (!message.message || !message.message.trim()) return;
    const resolvedPhase = resolveChatPhase(
      { phase: message.phase, is_wolf_chat: message.is_wolf_chat },
      current.phase
    );
    const normalizedMessage = {
      ...message,
      phase: resolvedPhase ?? message.phase
    };
    const id =
      normalizedMessage.action_id ||
      normalizedMessage.event_id ||
      normalizedMessage.id ||
      `${normalizedMessage.sid || ''}|${normalizedMessage.timestamp || ''}|${normalizedMessage.message}`;
    if (chatSeenRef.current.has(id)) return;
    chatSeenRef.current.add(id);
    const merged = [...(current.chat_messages || []), normalizedMessage];
    merged.sort((a, b) => {
      const tA = a.ts_ms ?? (a.timestamp ? new Date(a.timestamp).getTime() : 0);
      const tB = b.ts_ms ?? (b.timestamp ? new Date(b.timestamp).getTime() : 0);
      return tA - tB;
    });
    const next = {
      ...current,
      chat_messages: merged.slice(-200),
    };
    setGameState(next);
  }, [resolveChatPhase, setGameState]);

  const mapRecentChatItems = React.useCallback((items: unknown[] | null | undefined) => {
    if (!Array.isArray(items) || items.length === 0) return [];
    const fallbackPhase = useWerewolfStore.getState().gameState?.phase;
    return items.reduce<ChatMessage[]>((acc, msg) => {
      const record = getRecord(msg) ?? {};
      const tsMs = Number(record['ts_ms'] ?? 0);
      const content = String(record['content'] ?? '').trim();
      if (!content) return acc;
      acc.push({
        id: record['event_id'] ? String(record['event_id']) : record['id'] ? String(record['id']) : undefined,
        event_id: record['event_id'] ? String(record['event_id']) : undefined,
        action_id: record['action_id'] ? String(record['action_id']) : undefined,
        sid: record['sender_id'] !== undefined && record['sender_id'] !== null ? String(record['sender_id']) : undefined,
        nickname: record['sender_name'] ? String(record['sender_name']) : `agent_${record['sender_id'] ?? 'unknown'}`,
        message: content,
        timestamp: new Date(tsMs).toISOString(),
        ts_ms: tsMs,
        phase: resolveChatPhase(
          { phase: record['phase'] ? String(record['phase']) : undefined, channel: record['channel'] ? String(record['channel']) : undefined },
          fallbackPhase
        ),
        is_wolf_chat: record['channel'] === 'wolf',
      });
      return acc;
    }, []);
  }, [resolveChatPhase]);

  const seedRecentEvents = React.useCallback((items: any[] | null | undefined) => {
    if (!Array.isArray(items) || items.length === 0) return;
    items.forEach((envelope) => {
      if (envelope?.event_type === 'ww:phase:change') {
        applyPhaseChange(envelope);
        if (envelope?.id) trackLastEventId(envelope.id);
        return;
      }
      if (!['ww:night:action', 'ww:day:vote', 'ww:chat:day'].includes(envelope?.event_type)) return;
      const item = buildActionFeedItem(envelope);
      if (item) pushAction(item);
      if (envelope?.id) trackLastEventId(envelope.id);
    });
  }, [applyPhaseChange, buildActionFeedItem, pushAction, trackLastEventId]);

  const backfillRoomEvents = React.useCallback(async () => {
    if (backfillEventsRef.current) return;
    const afterId = lastEventIdRef.current;
    const initial = !afterId;
    if (initial) {
      if (initialEventsRef.current) return;
      initialEventsRef.current = true;
    }
    backfillEventsRef.current = true;
    try {
      const history = await fetchRoomEventHistory(
        roomId,
        100,
        undefined,
        initial ? undefined : afterId,
        WEREWOLF_EVENT_TYPES,
        true
      );
      const items = history.items || [];
      items.forEach((entry) => {
        if (entry.event_type === 'ww:phase:change') {
          applyPhaseChange(entry);
          if (entry.id) trackLastEventId(entry.id);
          return;
        }
        const item = buildActionFeedItem(entry);
        if (item) pushAction(item);
        if (entry.id) trackLastEventId(entry.id);
      });
      if (history.last_id) lastEventIdRef.current = history.last_id;
    } catch {
    } finally {
      backfillEventsRef.current = false;
    }
  }, [applyPhaseChange, buildActionFeedItem, pushAction, roomId, trackLastEventId]);

  const backfillRoomChat = React.useCallback(async () => {
    if (backfillChatRef.current) return;
    const afterId = lastChatIdRef.current;
    const initial = !afterId;
    if (initial) {
      if (initialChatRef.current) return;
      initialChatRef.current = true;
    }
    backfillChatRef.current = true;
    try {
      const history = await fetchRoomChatHistory(roomId, 100, undefined, initial ? undefined : afterId);
      const items = history.items || [];
      items.forEach((msg) => {
        const content = String(msg.content || '').trim();
        if (!content) return;
        appendChat({
          id: msg.event_id || msg.id,
          event_id: msg.event_id || undefined,
          action_id: msg.action_id || undefined,
          sid: msg.sender_id !== undefined && msg.sender_id !== null ? String(msg.sender_id) : undefined,
          nickname: msg.sender_name || `agent_${msg.sender_id ?? 'unknown'}`,
          message: content,
          timestamp: new Date(msg.ts_ms).toISOString(),
          ts_ms: msg.ts_ms,
          is_wolf_chat: msg.channel === 'wolf',
        });
        if (msg.id) trackLastChatId(msg.id);
      });
      if (history.last_id) lastChatIdRef.current = history.last_id;
    } catch {
    } finally {
      backfillChatRef.current = false;
    }
  }, [appendChat, roomId, trackLastChatId]);


  useSpectatorSocket({
    namespace: 'werewolf',
    tableId: roomId,
    events: {
      'room:state': (data) => {
        const mapped = mapWerewolfRoomState(data);
        if (data?.last_event_id) lastEventIdRef.current = String(data.last_event_id);
        if (data?.last_chat_id) lastChatIdRef.current = String(data.last_chat_id);
        if (mapped) {
          const history = pendingHistory.current;
          const recent = mapRecentChatItems(data?.recent_chat);
          const existing = (mapped.chat_messages || [])
            .map((msg) => ({
              ...msg,
              phase: resolveChatPhase({ phase: msg.phase, is_wolf_chat: msg.is_wolf_chat }, mapped.phase)
            }))
            .filter((msg) => Boolean(msg.message && String(msg.message).trim()));
          const merged = [...recent, ...(history || []), ...existing];
          const seen = new Set<string>();
          const deduped = merged.filter((item) => {
            const key = item.event_id || item.id || `${item.sid || ''}|${item.timestamp || ''}|${item.message}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          });
          const normalized = deduped
            .slice()
            .sort((a, b) => {
              const tA = a.ts_ms ?? (a.timestamp ? new Date(a.timestamp).getTime() : 0);
              const tB = b.ts_ms ?? (b.timestamp ? new Date(b.timestamp).getTime() : 0);
              return tA - tB;
            })
            .slice(-200);
          chatSeenRef.current = new Set(
            normalized.map((item) => item.event_id || item.id || `${item.sid || ''}|${item.timestamp || ''}|${item.message}`)
          );
          mapped.chat_messages = normalized;
          pendingHistory.current = null;
          setGameState(mapped);
          setLoadStatus('ready');
        }
        if (data?.recent_events) seedRecentEvents(data.recent_events);
        backfillRoomEvents();
        backfillRoomChat();
      },
      'room:update': (data) => {
        if (data?.id) trackLastEventId(data.id);
        if (data?.payload?.type === 'game_finish') {
          setLoadStatus('ended');
        }
      },
      'ww:day:vote': (data) => {
        if (data?.id) trackLastEventId(data.id);
        applyVoteUpdate(data);
        const item = buildActionFeedItem(data);
        if (item) pushAction(item);
      },
      'ww:phase:change': (data) => {
        if (data?.id) trackLastEventId(data.id);
        applyPhaseChange(data);
        // Detailed results are derived from room state to keep action logs consistent.
      },
      'ww:night:action': (data) => {
        if (data?.id) trackLastEventId(data.id);
        const item = buildActionFeedItem(data);
        if (item) {
          pushAction(item);
        }
      },
      'ww:chat:day': (data) => {
        const envelope = data?.event_type ? data : null;
        const inner = envelope?.payload ?? data;
        const payload = inner?.payload || {};
        const content = String(payload.msg || payload.content || '').trim();
        const meta = payload?.meta || {};
        const isTimeout = meta?.reason === 'timeout' || meta?.auto === true;
        if (!content && !isTimeout) return;
        const chatId = envelope?.event_id || inner?.event_id || envelope?.id || inner?.id;
        const tsMs = Number(envelope?.ts_ms ?? inner?.ts_ms ?? Date.now());
        if (envelope?.id) trackLastChatId(envelope.id);
        if (content) {
          appendChat({
            id: chatId ? String(chatId) : undefined,
            event_id: envelope?.event_id || inner?.event_id,
            action_id: envelope?.action_id || inner?.action_id,
            nickname: inner?.actor_name || payload.actor_name || payload.sender_name || String(inner?.actor_id || 'player'),
            message: content,
            timestamp: new Date(tsMs).toISOString(),
            ts_ms: tsMs,
            sid: String(inner?.actor_id || payload.sender_id || 'player'),
            phase: inner?.phase || payload?.phase,
          });
        }
        const item = buildActionFeedItem(data);
        if (item) pushAction(item);
      },
      'ww:chat:wolf': (data) => {
        const envelope = data?.event_type ? data : null;
        const inner = envelope?.payload ?? data;
        const payload = inner?.payload || {};
        const content = String(payload.msg || payload.content || '').trim();
        if (!content) return;
        const chatId = envelope?.event_id || inner?.event_id || envelope?.id || inner?.id;
        const tsMs = Number(envelope?.ts_ms ?? inner?.ts_ms ?? Date.now());
        if (envelope?.id) trackLastChatId(envelope.id);
        appendChat({
          id: chatId ? String(chatId) : undefined,
          event_id: envelope?.event_id || inner?.event_id,
          action_id: envelope?.action_id || inner?.action_id,
          nickname: inner?.actor_name || payload.actor_name || payload.sender_name || String(inner?.actor_id || 'player'),
          message: content,
          timestamp: new Date(tsMs).toISOString(),
          ts_ms: tsMs,
          sid: String(inner?.actor_id || payload.sender_id || 'player'),
          is_wolf_chat: true,
          phase: inner?.phase || payload?.phase,
        } as any);
      },
      'room:chat': (data) => {
        const envelope = data?.event_type ? data : null;
        const payload = envelope?.payload ?? data?.payload ?? data ?? {};
        const content = String(payload.content || payload.msg || '').trim();
        if (!content) return;
        const chatId = envelope?.event_id || envelope?.id || payload?.event_id || payload?.id;
        const tsMs = Number(envelope?.ts_ms ?? payload?.ts_ms ?? Date.now());
        if (envelope?.id) trackLastChatId(envelope.id);
        appendChat({
          id: chatId ? String(chatId) : undefined,
          event_id: envelope?.event_id || payload?.event_id,
          action_id: envelope?.action_id || payload?.action_id,
          nickname: payload.sender_name || payload.actor_name || String(payload.sender_id || payload.actor_id || 'player'),
          message: content,
          timestamp: new Date(tsMs).toISOString(),
          ts_ms: tsMs,
          sid: String(payload.sender_id || payload.actor_id || 'player'),
          phase: payload?.phase,
        });
      },
      connect: () => setConnected(true),
      disconnect: () => setConnected(false),
    }
  });

  React.useEffect(() => {
    if (!gameState) return;
    const tick = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      backfillRoomEvents();
      backfillRoomChat();
    };
    const interval = setInterval(tick, BACKFILL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [backfillRoomChat, backfillRoomEvents, gameState?.phase]);

  React.useEffect(() => {
    const timeout = setTimeout(() => {
      if (!useWerewolfStore.getState().gameState) {
        setLoadStatus('error');
      }
    }, 8000);
    return () => clearTimeout(timeout);
  }, []);

  const winnerMessage = React.useMemo(() => {
    if (winnerLabels.length === 0) return undefined;
    const first = winnerLabels[0];
    if (first.includes('NO CONTEST')) return first;
    return winnerLabels.length > 1
      ? `WINNERS: ${winnerLabels.join(' · ')}`
      : `WINNER: ${first}`;
  }, [winnerLabels]);

  const isTerminalGame = gameState?.phase === 'finished';

  if (isTerminalGame) {
    return (
      <div className={`min-h-screen flex items-center justify-center font-mono ${
        isAgent ? 'bg-black text-emerald-400' : 'bg-slate-50 text-slate-500'
      }`}>
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="text-4xl">🏆</div>
          <div className="text-lg font-semibold">Game Over</div>
          {winnerMessage ? (
            <div className={`text-sm font-semibold tracking-wide ${
              isAgent ? 'text-emerald-200' : 'text-sky-700'
            }`}>
              {winnerMessage}
            </div>
          ) : (
            <div className="text-xs opacity-70">Awaiting winner declaration.</div>
          )}
          <div className="text-xs opacity-70">Return to the lobby to watch active games.</div>
        </div>
      </div>
    );
  }

  if (!gameState) {
    if (loadStatus === 'ended') {
      return (
        <div className={`min-h-screen flex items-center justify-center font-mono ${
          isAgent ? 'bg-black text-emerald-400' : 'bg-slate-50 text-slate-500'
        }`}>
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="text-4xl">🏆</div>
            <div className="text-lg font-semibold">Game Over</div>
            {winnerMessage ? (
              <div className={`text-sm font-semibold tracking-wide ${
                isAgent ? 'text-emerald-200' : 'text-sky-700'
              }`}>
                {winnerMessage}
              </div>
            ) : (
              <div className="text-xs opacity-70">Awaiting winner declaration.</div>
            )}
            <div className="text-xs opacity-70">Return to the lobby to watch active games.</div>
          </div>
        </div>
      );
    }

    if (loadStatus === 'error') {
      return (
        <div className={`min-h-screen flex items-center justify-center font-mono ${
          isAgent ? 'bg-black text-emerald-400' : 'bg-slate-50 text-slate-500'
        }`}>
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="text-4xl">⚠️</div>
            <div className="text-lg font-semibold">Unable to load this game.</div>
            <div className="text-xs opacity-70">Please try again later.</div>
          </div>
        </div>
      );
    }

    return (
      <div className={`min-h-screen flex items-center justify-center font-mono ${
        isAgent ? 'bg-black text-emerald-400' : 'bg-slate-50 text-slate-500'
      }`}>
        <div className="animate-pulse flex flex-col items-center gap-4">
          {isAgent ? (
            <>
              <div className="text-4xl">🦞</div>
              <div>SYNCHRONIZING NEURAL LINK...</div>
            </>
          ) : (
            <>
              <div className="w-12 h-12 border-4 border-slate-200 border-t-sky-500 rounded-full animate-spin"></div>
              <div>Loading game state...</div>
            </>
          )}
        </div>
      </div>
    );
  }

  const currentPhaseKey = gameState.phase ? normalizeWerewolfPhase(gameState.phase) : 'unknown';
  const formatPhase = (value: string) => value.replace(/_/g, ' ').toUpperCase();
  const phaseLabel = formatPhase(currentPhaseKey || 'unknown');
  const dayLabel = `DAY ${Math.max(1, gameState.day_count || 0)}`;
  const endReasonLabel = resolveEndReasonLabel(gameState.phase_reason);
  const showEndReason = currentPhaseKey === 'finished' && Boolean(endReasonLabel);
  const phaseRank: Record<string, number> = {
    night: 0,
    day_discussion: 1,
    day_voting: 2,
    day: 1,
    finished: 3,
    setup: -1
  };
  const isLatePhase = (phase: string) => phase === 'finished';
  const phaseScore = (phase: string) => {
    const idx = phaseRank[phase];
    if (Number.isFinite(idx)) {
      if (!isLatePhase(currentPhaseKey) && isLatePhase(phase)) {
        return idx - 100;
      }
      return idx;
    }
    return -999;
  };
  const buildPhaseGroups = <T extends { phase?: string; ts_ms?: number; timestamp?: string | null; event_id?: string; id?: string }>(
    items: T[]
  ) => {
    const groups = new Map<string, T[]>();
    items.forEach((item) => {
      const raw = item.phase ? String(item.phase) : '';
      const normalized = raw ? normalizeWerewolfPhase(raw) : currentPhaseKey;
      const phase = normalized || currentPhaseKey;
      if (!groups.has(phase)) groups.set(phase, []);
      groups.get(phase)?.push(item);
    });
    if (!groups.has(currentPhaseKey)) groups.set(currentPhaseKey, []);
    return Array.from(groups.keys())
      .sort((a, b) => {
        if (a === currentPhaseKey && b === currentPhaseKey) return 0;
        if (a === currentPhaseKey) return -1;
        if (b === currentPhaseKey) return 1;
        return phaseScore(b) - phaseScore(a);
      })
      .map((phase) => ({ phase, items: (groups.get(phase) || []).slice().sort(compareByEventTimeDesc) }));
  };
  const actionPhaseGroups = buildPhaseGroups(actionPanelItems);
  const chatPhaseGroups = buildPhaseGroups(chatPanelItems);
  const currentActionGroup = actionPhaseGroups.find((group) => group.phase === currentPhaseKey);
  const currentChatGroup = chatPhaseGroups.find((group) => group.phase === currentPhaseKey);
  const actionCount = currentActionGroup?.items.length ?? 0;
  const chatCount = currentChatGroup?.items.length ?? 0;
  const stageWidth = stageSize.width || WEREWOLF_STAGE_WIDTH;
  const stageHeight = stageSize.height || WEREWOLF_STAGE_HEIGHT;
  const stageScale = Math.min(1, stageWidth / WEREWOLF_STAGE_WIDTH, stageHeight / WEREWOLF_STAGE_HEIGHT);
  const tableSize = Math.min(WEREWOLF_STAGE_WIDTH, WEREWOLF_STAGE_HEIGHT) * 0.72;
  const tableRadius = tableSize / 2;
  const seatRadius = Math.max(140, tableRadius - 44);
  const lineRadius = Math.max(120, seatRadius - 36);

  return (
    <div className={`flex flex-row h-screen overflow-hidden font-mono transition-colors duration-500 ${
      isAgent ? 'bg-black text-gray-200' : 'bg-slate-50 text-slate-800'
    }`}>
      {/* Right Chat Panel */}
      <div
        className={`order-3 w-72 border-l px-5 py-4 overflow-x-hidden ${
          isAgent ? 'border-emerald-500/20 bg-black/60 text-emerald-100' : 'border-sky-200/80 bg-sky-50/80 text-sky-800'
        }`}
      >
        <div className="text-[13px] font-bold uppercase tracking-[0.32em] opacity-80">Chat ({chatCount})</div>
        <div className={`mt-2 text-[11px] font-semibold uppercase tracking-[0.3em] ${
          isAgent ? 'text-emerald-200/70' : 'text-sky-600/70'
        }`}>
          {dayLabel} · {phaseLabel}
        </div>
        <div className="mt-3 space-y-3 text-sm max-h-[calc(100vh-220px)] overflow-y-auto pr-1 overflow-x-hidden">
          {chatCount === 0 ? (
            <div className="opacity-70">No messages yet.</div>
          ) : (
            chatPhaseGroups.map((group) => {
              const isCurrent = group.phase === currentPhaseKey;
              return (
                <div key={`chat-phase-${group.phase}`} className="space-y-2">
                  <div className={`flex items-center justify-between text-[11px] font-bold uppercase tracking-[0.3em] ${
                    isCurrent
                      ? (isAgent ? 'text-emerald-200' : 'text-sky-800')
                      : (isAgent ? 'text-emerald-200/70' : 'text-sky-700/70')
                  }`}>
                    <span>{formatPhase(group.phase)}</span>
                    <span className={`text-[9px] px-2 py-0.5 rounded-full border ${
                      isCurrent
                        ? (isAgent ? 'border-emerald-400/40' : 'border-sky-400/40')
                        : (isAgent ? 'border-emerald-400/20' : 'border-sky-400/20')
                    }`}>
                      {isCurrent ? 'LIVE' : 'PAST'}
                    </span>
                  </div>
                  {isCurrent && (
                    group.items.length === 0 ? (
                      <div className="opacity-60 text-xs">No messages yet.</div>
                    ) : (
                      group.items.map((item, idx) => (
                        <div
                          key={item.event_id || item.id || `${item.sid || 'system'}-${item.ts_ms || idx}`}
                          className={`leading-snug flex items-start gap-2 ${
                            isAgent ? 'text-emerald-100' : 'text-sky-800'
                          }`}
                        >
                          <span className="text-base">{item.is_wolf_chat ? '🐺' : '💬'}</span>
                          <div className="flex flex-col gap-0.5">
                            <span className={`text-[10px] uppercase tracking-[0.25em] ${
                              isAgent ? 'text-emerald-300/70' : 'text-sky-500'
                            }`}>
                              {resolveDisplayName(item.sid)}
                            </span>
                            <span>{item.message}</span>
                          </div>
                        </div>
                      ))
                    )
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      <div className="order-2 flex-1 relative">
        <DayNightCycle phase={gameState.phase} isAgent={isAgent}>
          {/* Stage Top: Current Action / Phase / Speaking */}
          <div className="absolute left-0 right-0 top-6 z-20 pointer-events-none px-6">
            <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-4">
              <div className={`justify-self-start translate-x-6 w-[22rem] h-[112px] px-5 py-4 rounded-3xl border shadow-2xl backdrop-blur-xl ${
                isAgent
                  ? 'bg-black/80 border-emerald-500/40 text-white shadow-[0_30px_80px_rgba(16,185,129,0.25)]'
                  : 'bg-white/90 border-sky-200 text-sky-800 shadow-[0_30px_80px_rgba(14,165,233,0.15)]'
              }`}>
                <div className="text-[10px] uppercase tracking-[0.25em] opacity-70">Action</div>
                {currentActionItem ? (
                  <div className="mt-1 flex flex-col gap-1">
                    <div className={`text-sm font-semibold tracking-wide ${isAgent ? 'text-emerald-100' : 'text-sky-700'}`}>
                      {formatActionActorLabel(currentActionItem.actorLabel ?? 'UNKNOWN')}
                    </div>
                    <div className={`text-xs ${isAgent ? 'text-emerald-200' : 'text-sky-600'}`}>
                      {currentActionItem.icon ? `${currentActionItem.icon} ` : ''}{currentActionItem.content || currentActionItem.message}
                    </div>
                  </div>
                ) : (
                  <div className={`mt-1 text-sm font-semibold ${isAgent ? 'text-emerald-200' : 'text-sky-600'}`}>
                    No action yet
                  </div>
                )}
              </div>

              <div className={`justify-self-center px-6 py-3 rounded-full border shadow-2xl backdrop-blur-xl ${
                isAgent
                  ? 'bg-black/80 border-emerald-500/40 text-white shadow-[0_30px_80px_rgba(16,185,129,0.25)]'
                  : 'bg-white/90 border-sky-200 text-sky-800 shadow-[0_30px_80px_rgba(14,165,233,0.15)]'
              }`}>
                <div className="text-[10px] uppercase tracking-[0.25em] opacity-70">{dayLabel}</div>
                <div className={`text-sm font-bold tracking-wide ${isAgent ? 'text-emerald-100' : 'text-sky-700'}`}>
                  {phaseLabel}
                </div>
                {showEndReason && (
                  <div className={`mt-1 text-[10px] font-semibold uppercase tracking-[0.2em] ${
                    isAgent ? 'text-amber-200' : 'text-amber-700'
                  }`}>
                    {endReasonLabel}
                  </div>
                )}
              </div>

              <div className={`justify-self-end -translate-x-6 w-[22rem] h-[112px] px-5 py-4 rounded-3xl border shadow-2xl backdrop-blur-xl ${
                isAgent
                  ? 'bg-black/80 border-emerald-500/40 text-white shadow-[0_30px_80px_rgba(16,185,129,0.25)]'
                  : 'bg-white/90 border-sky-200 text-sky-800 shadow-[0_30px_80px_rgba(14,165,233,0.15)]'
              }`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-[0.25em] opacity-70">Speaking</span>
                </div>
                {activeMessage ? (
                  <div className="mt-1 flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex h-3 w-3 rounded-full animate-pulse" style={{ background: playerMeta.get(activeMessage.sid)?.color }} />
                      <span className={`text-sm font-semibold tracking-wide ${isAgent ? 'text-emerald-100' : 'text-sky-700'}`}>
                        {resolveDisplayName(activeMessage.sid)}
                      </span>
                    </div>
                    <div className={`text-xs ${isAgent ? 'text-emerald-200' : 'text-sky-600'}`}>
                      {activeMessage.content}
                    </div>
                  </div>
                ) : (
                  <div className={`mt-1 text-sm font-semibold ${isAgent ? 'text-emerald-200' : 'text-sky-600'}`}>
                    No active speaker
                  </div>
                )}
              </div>
            </div>
          </div>
          {victoryBanner && (
            <div className="absolute left-1/2 top-24 -translate-x-1/2 z-20 pointer-events-none">
              <div className={`px-6 py-2 rounded-full border text-sm font-bold tracking-wide ${
                isAgent
                  ? 'bg-amber-500/15 border-amber-300/60 text-amber-100 shadow-[0_0_24px_rgba(251,191,36,0.45)]'
                  : 'bg-sky-100 border-sky-200 text-sky-800 shadow-lg'
              }`}>
                <div>{victoryBanner.message}</div>
                {showEndReason && (
                  <div className={`mt-1 text-[10px] font-semibold uppercase tracking-[0.2em] ${
                    isAgent ? 'text-amber-200' : 'text-amber-700'
                  }`}>
                    {endReasonLabel}
                  </div>
                )}
              </div>
            </div>
          )}
          <div className="absolute left-1/2 bottom-16 -translate-x-1/2 z-20 pointer-events-none">
            <div className={`px-5 py-2 rounded-full border text-xs font-semibold tracking-[0.3em] ${
              isAgent
                ? 'bg-black/80 border-emerald-500/40 text-emerald-200'
                : 'bg-white/90 border-sky-200 text-sky-700'
            }`}>
              {phaseRemainingMs !== null ? `TIMER ${Math.ceil(phaseRemainingMs / 1000)}s` : 'TIMER --'}
            </div>
          </div>
          <div ref={stageContainerRef} className="absolute inset-0">
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
              <div
                className="relative"
                style={{
                  width: WEREWOLF_STAGE_WIDTH,
                  height: WEREWOLF_STAGE_HEIGHT,
                  transform: `scale(${stageScale || 1})`,
                  transformOrigin: 'center center'
                }}
              >
                <WerewolfTableStage
                  players={gameState.players}
                  votes={gameState.votes || {}}
                  activeMessage={activeMessage}
                  isAgent={isAgent}
                  tableSize={tableSize}
                  seatRadius={seatRadius}
                  lineRadius={lineRadius}
                />
              </div>
            </div>
          </div>
        </DayNightCycle>
      </div>

      {/* Left Actions Panel */}
      <div
        className={`order-1 w-72 border-r px-5 py-4 overflow-x-hidden ${
          isAgent ? 'border-emerald-500/20 bg-black/60 text-emerald-100' : 'border-sky-200/80 bg-sky-50/80 text-sky-800'
        }`}
      >
        <div className="text-[13px] font-bold uppercase tracking-[0.32em] opacity-80">Actions ({actionCount})</div>
        <div className={`mt-2 text-[11px] font-semibold uppercase tracking-[0.3em] ${
          isAgent ? 'text-emerald-200/70' : 'text-sky-600/70'
        }`}>
          {dayLabel} · {phaseLabel}
        </div>
        <div className="mt-3 space-y-3 text-sm max-h-[calc(100vh-220px)] overflow-y-auto pr-1 overflow-x-hidden">
          {actionCount === 0 ? (
            <div className="opacity-70">No key actions yet.</div>
          ) : (
            actionPhaseGroups.map((group) => {
              const isCurrent = group.phase === currentPhaseKey;
              return (
                <div key={`action-phase-${group.phase}`} className="space-y-2">
                  <div className={`flex items-center justify-between text-[11px] font-bold uppercase tracking-[0.3em] ${
                    isCurrent
                      ? (isAgent ? 'text-emerald-200' : 'text-sky-800')
                      : (isAgent ? 'text-emerald-200/70' : 'text-sky-700/70')
                  }`}>
                    <span>{formatPhase(group.phase)}</span>
                    <span className={`text-[9px] px-2 py-0.5 rounded-full border ${
                      isCurrent
                        ? (isAgent ? 'border-emerald-400/40' : 'border-sky-400/40')
                        : (isAgent ? 'border-emerald-400/20' : 'border-sky-400/20')
                    }`}>
                      {isCurrent ? 'LIVE' : 'PAST'}
                    </span>
                  </div>
                  {isCurrent && (
                    group.items.length === 0 ? (
                      <div className="opacity-60 text-xs">No actions yet.</div>
                    ) : (
                      group.items.map((item) => (
                        <div
                          key={item.id}
                          className={`leading-snug flex items-start gap-2 ${
                            item.tone === 'action'
                              ? (isAgent ? 'text-emerald-100 font-semibold' : 'text-sky-800 font-semibold')
                              : (isAgent ? 'text-emerald-200/70' : 'text-sky-600')
                          }`}
                        >
                          {item.tone === 'system' ? (() => {
                            const parsed = splitSystemMessage(item.content);
                            return (
                              <div className="flex items-center gap-2 whitespace-nowrap">
                                <span className="text-base">{parsed.icon}</span>
                                <span className="text-xs">{parsed.text}</span>
                              </div>
                            );
                          })() : (
                            <>
                              <span className="text-base">
                                {item.icon || '🎯'}
                              </span>
                              <div className="flex flex-col gap-0.5">
                                <span className={`text-[10px] uppercase tracking-[0.25em] ${
                                  isAgent ? 'text-emerald-300/70' : 'text-sky-500'
                                }`}>
                                  {formatActionActorLabel(item.actor || 'TOWN')}
                                </span>
                                <span>{item.content}</span>
                              </div>
                            </>
                          )}
                        </div>
                      ))
                    )
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

'use client';

import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useParams, useSearchParams } from 'next/navigation';
import { useSpectatorSocket } from '@/hooks/useSpectatorSocket';
import { useTexasStore } from '@/store/texasStore';
import { useUiMode } from '@/components/UiModeProvider';
import PlayerSeat, { SEAT_AVATARS } from '@/components/texas/PlayerSeat';
import CommunityCards from '@/components/texas/CommunityCards';
import ChipStream from '@/components/texas/ChipStream';
import EventTicker from '@/components/texas/EventTicker';
import { mapTexasRoomState } from '@/lib/stateAdapters';
import { fetchRoomChatHistory, fetchRoomEventHistory } from '@/lib/roomsApi';
import type { RoomChatMessage } from '@/lib/roomsApi';
import { ensureSocketMode } from '@/lib/socket';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';
import seatLayout from '@/config/texasSeatLayout.json';

type ActionItem = { id: string; kind: 'action'; action: string; message: string; phase?: string; handIndex: number; actorId?: string; ts_ms?: number; stream_id?: string };
type ChatItem = { id: string; kind: 'chat'; message: string; phase?: string; handIndex: number; senderId?: string; ts_ms?: number; stream_id?: string };
type TexasEvent = {
  event_type?: string;
  payload?: {
    hand_index?: number;
    amount?: number;
    phase?: string;
    stacks?: Record<string, number>;
    bets?: Record<string, number>;
    pot?: number;
    board?: unknown[];
    actor_id?: string | number;
    winner_ids?: (string | number)[];
    winner_id?: string | number;
    timers?: unknown;
    payouts?: Record<string, number>;
    sender_id?: string | number;
    sender_name?: string;
    actor_name?: string;
    content?: string;
    msg?: string;
    [key: string]: unknown;
  };
  id?: string;
  action_id?: string;
  event_id?: string;
  ts_ms?: number;
  actor_id?: string | number;
  next_actor_id?: string | number;
  hand_index?: number;
  amount?: number;
  phase?: string;
  payouts?: Record<string, number>;
  sender_id?: string | number;
  sender_name?: string;
  actor_name?: string;
  content?: string;
  msg?: string;
  chat_id?: string;
  meta?: {
    hand_index?: number;
    phase?: string;
    [key: string]: unknown;
  };
};
const BASE_STAGE_WIDTH = 1200;
const BASE_STAGE_HEIGHT = 820;
const TICKER_DURATION_MS = 1400;
const VICTORY_DURATION_MS = 2000;
const TABLE_SHIFT_X = -12;
const BACKFILL_INTERVAL_MS = 5000;

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

const compareByEventTimeDesc = (a: { ts_ms?: number; stream_id?: string }, b: { ts_ms?: number; stream_id?: string }) => {
  const tA = Number(a.ts_ms ?? 0);
  const tB = Number(b.ts_ms ?? 0);
  if (tA !== tB) return tB - tA;
  return compareStreamId(b.stream_id, a.stream_id);
};

const resolveDedupeId = (...candidates: Array<string | number | null | undefined>) => {
  for (const candidate of candidates) {
    if (candidate === null || candidate === undefined) continue;
    const value = String(candidate);
    if (value) return value;
  }
  return null;
};

interface SeatLayoutConfig {
  slotOffsets: Record<string, { x: number; y: number }>;
  elementOffsets: Record<string, { x: number; y: number }>;
}

export default function TexasTablePage() {
  const { tableId } = useParams() as { tableId: string };
  const searchParams = useSearchParams();
  const debugSeatLayout = searchParams.get('seatLayoutDebug') === '1';
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';
  const stageContainerRef = React.useRef<HTMLDivElement | null>(null);
  const stageFrameRef = React.useRef<HTMLDivElement | null>(null);
  const potRef = React.useRef<HTMLDivElement | null>(null);
  const [stageSize, setStageSize] = React.useState({ width: 0, height: 0 });
  const [seatAnchors, setSeatAnchors] = React.useState<Record<string, { x: number; y: number }>>({});
  const [potAnchor, setPotAnchor] = React.useState<{ x: number; y: number } | null>(null);
  const [settlementPulse, setSettlementPulse] = React.useState<{ id: string; payouts: Record<string, number> } | null>(null);
  const [victoryBanner, setVictoryBanner] = React.useState<{ id: string; message: string; winners: string[] } | null>(null);
  
  const { 
    gameState, 
    isConnected,
    setGameState, 
    addLog,
    clearLog,
    setConnected,
    reset
  } = useTexasStore();
  const [hasConnectedOnce, setHasConnectedOnce] = React.useState(false);
  const [loadStatus, setLoadStatus] = React.useState<'loading' | 'ready' | 'ended' | 'error'>('loading');
  const prevPhase = React.useRef<string | undefined>(undefined);
  const prevCurrentPlayer = React.useRef<string | undefined>(undefined);
  const [activeSpeakerSid, setActiveSpeakerSid] = React.useState<string | undefined>(undefined);
  const activeSpeakerTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const [lastActionSid, setLastActionSid] = React.useState<string | undefined>(undefined);
  const lastActionTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const [ticker, setTicker] = React.useState<{ message: string; tone?: 'action' | 'win' | 'system' } | null>(null);
  const [layoutNonce, setLayoutNonce] = React.useState(0);
  const [layoutConfig, setLayoutConfig] = React.useState<SeatLayoutConfig>(seatLayout);
  const refreshRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevHandRef = React.useRef<number | null>(null);
  const prevPlayerStatusRef = React.useRef<Record<string, string>>({});
  const [handStartStacks, setHandStartStacks] = React.useState<Record<string, number>>({});
  const [handStartHand, setHandStartHand] = React.useState<number | null>(null);
  const [actionItems, setActionItems] = React.useState<ActionItem[]>([]);
  const [chatItems, setChatItems] = React.useState<ChatItem[]>([]);
  const [actionPhaseCollapse, setActionPhaseCollapse] = React.useState<Record<string, boolean>>({});
  const [chatPhaseCollapse, setChatPhaseCollapse] = React.useState<Record<string, boolean>>({});
  const actionSeenRef = React.useRef<Set<string>>(new Set());
  const chatSeenRef = React.useRef<Set<string>>(new Set());
  const lastEventIdRef = React.useRef<string | null>(null);
  const lastChatIdRef = React.useRef<string | null>(null);
  const backfillEventsRef = React.useRef(false);
  const backfillChatRef = React.useRef(false);
  const initialEventsRef = React.useRef(false);
  const initialChatRef = React.useRef(false);
  const layoutConfigRef = React.useRef<SeatLayoutConfig>(layoutConfig);
  const elementOffsets = React.useMemo(() => layoutConfig?.elementOffsets || {}, [layoutConfig]);
  const getElementOffset = React.useCallback((key: string, fallbackKey?: string) => {
    const raw = elementOffsets?.[key] ?? (fallbackKey ? elementOffsets?.[fallbackKey] : undefined);
    const x = Number(raw?.x);
    const y = Number(raw?.y);
    return {
      x: Number.isFinite(x) ? x : 0,
      y: Number.isFinite(y) ? y : 0
    };
  }, [elementOffsets]);
  const winnerOffset = getElementOffset('winner', 'round');
  const winnerDragRef = React.useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);

  React.useEffect(() => {
    layoutConfigRef.current = layoutConfig;
  }, [layoutConfig]);

  React.useEffect(() => {
    if (typeof window === 'undefined') return;
    if (tableId) {
      window.localStorage.setItem('texas:last_table_id', String(tableId));
    }
  }, [tableId]);

  React.useEffect(() => {
    let mounted = true;
    const loadLayout = async () => {
      try {
        const res = await fetch('/api/texas-seat-layout');
        if (!res.ok) return;
        const data = await res.json();
        if (mounted && data) {
          setLayoutConfig(data);
        }
      } catch {
      }
    };
    loadLayout();
    return () => {
      mounted = false;
    };
  }, []);

  const getAvatarForSid = React.useCallback((sid?: string | null) => {
    if (!sid) return '🧑';
    const current = useTexasStore.getState().gameState;
    if (current) {
      const idx = current.players.findIndex((p) => p.sid === String(sid));
      if (idx >= 0) {
        return SEAT_AVATARS[idx % SEAT_AVATARS.length];
      }
    }
    let hash = 0;
    const str = String(sid);
    for (let i = 0; i < str.length; i += 1) {
      hash = (hash * 31 + str.charCodeAt(i)) | 0;
    }
    return SEAT_AVATARS[Math.abs(hash) % SEAT_AVATARS.length];
  }, []);


  const EVENT_ACTION_LABELS: Record<string, string> = React.useMemo(() => ({
    'tx:fold': 'fold',
    'tx:check': 'check',
    'tx:call': 'call',
    'tx:bet': 'bet',
    'tx:raise': 'raise',
    'tx:all_in': 'all-in',
    'tx:vote_end': 'vote_end',
    'tx:hand:result': 'hand_result',
    'tx:settlement': 'settlement',
  }), []);
  const SYSTEM_ACTIONS = React.useMemo(() => new Set(['hand_result', 'settlement']), []);
  const TEXAS_EVENT_TYPES = React.useMemo(() => [
    'tx:fold',
    'tx:check',
    'tx:call',
    'tx:bet',
    'tx:raise',
    'tx:all_in',
    'tx:vote_end',
    'tx:hand:result',
    'tx:settlement',
    'tx:phase:change',
  ], []);

  const normalizePhase = React.useCallback((phase?: string | null) => {
    if (!phase) return null;
    const normalized = String(phase).trim().toLowerCase();
    return normalized || null;
  }, []);

  const formatPhase = React.useCallback((phase?: string | null) => {
    if (!phase) return 'UNKNOWN';
    return String(phase).replace(/_/g, ' ').toUpperCase();
  }, []);

  const buildActionKey = React.useCallback(
    (handIndex: number, phase: string | null | undefined, actionLabel: string, actorId: string, amount?: number) => {
      const phaseKey = phase ? String(phase) : 'na';
      return `action-${handIndex}-${phaseKey}-${actionLabel}-${actorId}-${amount ?? ''}`;
    },
    []
  );

  const appendActionItem = React.useCallback(
    (
      actionLabel: string,
      event: TexasEvent,
      handIndex: number,
      options?: { eventId?: string | null; actionId?: string | null; streamId?: string | null; tsMs?: number }
    ) => {
      const actorId = event?.actor_id != null ? String(event.actor_id) : '';
      const fallbackPhase = normalizePhase(useTexasStore.getState().gameState?.phase);
      const phase = normalizePhase(event?.phase || event?.payload?.phase || event?.meta?.phase || undefined) || fallbackPhase;
      if (!phase) return;
      const amountRaw = event?.payload?.amount ?? event?.amount;
      const parsedAmount = amountRaw !== undefined ? Number(amountRaw) : undefined;
      const amount = Number.isFinite(parsedAmount) ? parsedAmount : undefined;
      const dedupeId = resolveDedupeId(options?.actionId, options?.eventId, options?.streamId);
      const key = dedupeId ?? buildActionKey(handIndex, phase, actionLabel, actorId, amount);
      if (actionSeenRef.current.has(key)) return;
      actionSeenRef.current.add(key);
      const payload = event?.payload || {};
      let message = '';
      if (actionLabel === 'hand_result' || actionLabel === 'settlement') {
        const payouts = payload?.payouts || event?.payouts || {};
        const winnerIds = Array.isArray(payload?.winner_ids)
          ? payload.winner_ids
          : Object.keys(payouts);
        if (winnerIds.length > 0) {
          const label = winnerIds.length > 1 ? 'WINNERS' : 'WINNER';
          message = `🏆 ${label}: ${winnerIds.map((id: string | number) => getAvatarForSid(String(id))).join(' · ')}`;
        } else {
          message = actionLabel === 'hand_result' ? '🏆 HAND RESULT' : '🏁 SETTLEMENT';
        }
      } else {
        const avatar = getAvatarForSid(actorId);
        const displayAction = actionLabel.replace(/_/g, ' ').toUpperCase();
        message = `${avatar} ${displayAction}${amount !== undefined ? ` ${amount}` : ''}`;
      }
      setActionItems((prev) => [
        ...prev,
        {
          id: key,
          kind: 'action',
          action: actionLabel,
          message,
          phase,
          handIndex,
          actorId,
          ts_ms: options?.tsMs,
          stream_id: options?.streamId ?? undefined,
        }
      ]);
    },
    [buildActionKey, getAvatarForSid, normalizePhase]
  );

  const appendChatEntry = React.useCallback(
    (
      payload: { id?: string; action_id?: string | null; phase?: string | null; sender_id?: number | string | null; content?: string | null; ts_ms?: number; stream_id?: string },
      handIndex: number
    ) => {
      const fallbackPhase = normalizePhase(useTexasStore.getState().gameState?.phase);
      const phase = payload.phase ? normalizePhase(payload.phase) : fallbackPhase;
      if (!phase) return;
      const senderId = payload.sender_id != null ? String(payload.sender_id) : null;
      const content = String(payload.content || '');
      if (!content) return;
      const dedupeId = resolveDedupeId(payload.action_id, payload.id, payload.stream_id);
      const key = dedupeId || `chat-${handIndex}-${senderId}-${phase || 'na'}-${content}`;
      if (chatSeenRef.current.has(key)) return;
      chatSeenRef.current.add(key);
      setChatItems((prev) => {
        const next = [...prev];
        const avatar = getAvatarForSid(senderId);
        next.push({ id: key, kind: 'chat', message: `${avatar}: ${content}`, phase: phase || undefined, handIndex, senderId: senderId || undefined, ts_ms: payload.ts_ms, stream_id: payload.stream_id });
        return next;
      });
    },
    [getAvatarForSid, normalizePhase]
  );

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

  const requestRoomState = React.useCallback(() => {
    if (refreshRef.current) return;
    refreshRef.current = setTimeout(() => {
      refreshRef.current = null;
      const socket = ensureSocketMode('spectator');
      if (!socket) return;
      const roomId = Number(tableId);
      if (!Number.isFinite(roomId) || roomId <= 0) return;
      socket.emit('room:join', { room_id: roomId, role: 2 });
    }, 250);
  }, [tableId]);

  React.useEffect(() => {
    return () => {
      if (refreshRef.current) {
        clearTimeout(refreshRef.current);
        refreshRef.current = null;
      }
    };
  }, []);

  const applyLocalAction = React.useCallback((actionLabel: string, event: { actor_id?: string | number; payload?: { amount?: number }; amount?: number }) => {
    const allowed = new Set(['fold', 'check', 'call', 'bet', 'raise', 'all-in', 'all_in']);
    if (!allowed.has(actionLabel)) return;
    const current = useTexasStore.getState().gameState;
    if (!current) return;
    const actorId = event?.actor_id != null ? String(event.actor_id) : '';
    if (!actorId) return;
    const amountRaw = event?.payload?.amount ?? event?.amount;
    const amount = Number(amountRaw);
    const nextPlayers = current.players.map((player) => {
      if (player.sid !== actorId) return player;
      let status = player.status;
      if (actionLabel === 'fold') {
        status = 'folded';
      } else if (actionLabel === 'all-in' || actionLabel === 'all_in') {
        status = 'allin';
      } else if (player.status === 'folded' || player.status === 'allin') {
        status = player.status;
      } else {
        status = 'active';
      }
      let currentBet = player.current_bet ?? 0;
      if (Number.isFinite(amount) && ['bet', 'raise', 'call', 'all-in', 'all_in'].includes(actionLabel)) {
        currentBet = Math.max(currentBet, amount);
      }
      return {
        ...player,
        status,
        current_bet: currentBet,
      };
    });
    setGameState({ ...current, players: nextPlayers });
  }, [setGameState]);
  const exportSeatLayout = React.useCallback(() => {
    if (typeof window === 'undefined') return;
    const totalPlayers = gameState?.players?.length || 0;
    if (!totalPlayers) return;
    const key = `texas:seatLayout:${totalPlayers}`;
    const payload = window.localStorage.getItem(key) || '{}';
    const text = payload && payload !== '{}' ? payload : JSON.stringify({});
    const label = `[Texas SeatLayout] total=${totalPlayers}`;
    const write = navigator?.clipboard?.writeText;
    if (write) {
      write(text)
        .then(() => console.log(label, text))
        .catch(() => console.log(label, text));
    } else {
      console.log(label, text);
      window.prompt('Seat layout JSON', text);
    }
  }, [gameState?.players?.length]);
  const clearSeatLayout = React.useCallback(() => {
    if (typeof window === 'undefined') return;
    const totalPlayers = gameState?.players?.length || 0;
    if (!totalPlayers) return;
    const key = `texas:seatLayout:${totalPlayers}`;
    window.localStorage.removeItem(key);
    setLayoutNonce((value) => value + 1);
    console.log('[Texas SeatLayout] cleared', { totalPlayers });
  }, [gameState?.players?.length]);

  React.useEffect(() => {
    if (!ticker) return;
    const timeout = setTimeout(() => setTicker(null), TICKER_DURATION_MS);
    return () => clearTimeout(timeout);
  }, [ticker]);

  const resetHistory = React.useCallback(() => {
    actionSeenRef.current = new Set();
    chatSeenRef.current = new Set();
    setActionItems([]);
    setChatItems([]);
    setActionPhaseCollapse({});
    setChatPhaseCollapse({});
  }, []);

  const loadChatHistoryForHand = React.useCallback(async (handNumber: number) => {
    try {
      const limit = 100;
      let beforeId: string | undefined;
      const collected: RoomChatMessage[] = [];
      for (let i = 0; i < 20; i += 1) {
        const history = await fetchRoomChatHistory(tableId, limit, beforeId, undefined, handNumber);
        const batch = (history.items || [])
          .filter((msg) => Number.isFinite(Number(msg.hand_index)) && Number(msg.hand_index) === handNumber)
          .slice()
          .sort((a, b) => a.ts_ms - b.ts_ms);
        if (batch.length === 0) break;
        collected.unshift(...batch);
        if (batch.length < limit) break;
        beforeId = batch[0]?.id;
        if (!beforeId) break;
      }
      collected.forEach((msg) => {
        appendChatEntry(
          {
            id: msg.event_id || msg.id,
            action_id: msg.action_id ?? undefined,
            stream_id: msg.id,
            phase: msg.phase ?? undefined,
            sender_id: msg.sender_id ?? msg.sender_name ?? null,
            content: msg.content,
            ts_ms: msg.ts_ms,
          },
          handNumber
        );
        trackLastChatId(msg.id);
      });
    } catch {
    }
  }, [appendChatEntry, tableId, trackLastChatId]);

  const loadActionHistoryForHand = React.useCallback(async (handNumber: number) => {
    try {
      const limit = 200;
      const history = await fetchRoomEventHistory(tableId, limit, undefined, undefined, TEXAS_EVENT_TYPES);
      const items = (history.items || [])
        .filter((item) => EVENT_ACTION_LABELS[item.event_type])
        .map((item) => {
          const event = (item.payload || {}) as TexasEvent;
          const eventHand = Number(event?.payload?.hand_index ?? event?.hand_index ?? event?.meta?.hand_index);
          const actionLabel = EVENT_ACTION_LABELS[item.event_type];
          const isSystem = actionLabel ? SYSTEM_ACTIONS.has(actionLabel) : false;
          if (!Number.isFinite(eventHand) && !isSystem) {
            return null;
          }
          if (Number.isFinite(handNumber) && Number.isFinite(eventHand) && eventHand !== handNumber) {
            return null;
          }
          return {
            id: item.id,
            event_type: item.event_type,
            event,
            event_id: item.event_id,
            action_id: item.action_id ?? undefined,
            ts_ms: item.ts_ms
          };
        })
        .filter(Boolean) as Array<{ id: string; event_type: string; event: TexasEvent; event_id?: string; action_id?: string; ts_ms?: number }>;
      items.sort((a, b) => {
        const tA = Number(a.ts_ms ?? a.event?.ts_ms ?? 0);
        const tB = Number(b.ts_ms ?? b.event?.ts_ms ?? 0);
        return tA - tB;
      });
      items.forEach((item) => {
        const actionLabel = EVENT_ACTION_LABELS[item.event_type];
        if (!actionLabel) return;
        const eventHand = Number(item.event?.payload?.hand_index ?? item.event?.hand_index ?? item.event?.meta?.hand_index);
        const resolvedHand = Number.isFinite(eventHand) ? Number(eventHand) : handNumber;
        appendActionItem(actionLabel, item.event, resolvedHand, {
          eventId: item.event_id ?? undefined,
          actionId: item.action_id ?? undefined,
          streamId: item.id,
          tsMs: item.ts_ms,
        });
        trackLastEventId(item.id);
      });
    } catch {
    }
  }, [SYSTEM_ACTIONS, EVENT_ACTION_LABELS, TEXAS_EVENT_TYPES, appendActionItem, tableId, trackLastEventId]);

  React.useEffect(() => {
    if (!gameState) return;
    const handNumber = Number(gameState.hand_number ?? 0);
    const logHandCards = () => {
      if (process.env.NODE_ENV !== 'development') return;
      const snapshot = gameState.players.map((player) => ({
        player: player.nickname,
        sid: player.sid,
        cards: player.hole_cards,
      }));
      console.log('[Texas] hand cards', { handNumber, snapshot, board: gameState.community_cards });
    };
    if (prevHandRef.current === null || prevHandRef.current !== handNumber) {
      if (prevHandRef.current !== null) {
        const prevStatusMap = prevPlayerStatusRef.current || {};
        const newlyBusted = gameState.players.filter((player) => player.status === 'busted' && prevStatusMap[player.sid] !== 'busted');
        if (newlyBusted.length > 0) {
          const first = newlyBusted[0];
          const label = `${getAvatarForSid(first.sid)} OUT OF CHIPS — SPECTATE OR EXIT`;
          setTicker({ message: label, tone: 'system' });
        }
      }
      prevHandRef.current = handNumber;
      clearLog();
      setActiveSpeakerSid(undefined);
      const next: Record<string, number> = {};
      gameState.players.forEach((player) => {
        next[player.sid] = Number(player.chips ?? 0) + Number(player.current_bet ?? 0);
      });
      setHandStartStacks(next);
      setHandStartHand(handNumber);
      resetHistory();
      loadActionHistoryForHand(handNumber);
      if (Number.isFinite(handNumber)) {
        loadChatHistoryForHand(handNumber);
      }
      logHandCards();
      prevPlayerStatusRef.current = Object.fromEntries(
        gameState.players.map((player) => [player.sid, player.status])
      );
      return;
    }
    prevPlayerStatusRef.current = Object.fromEntries(
      gameState.players.map((player) => [player.sid, player.status])
    );
    setHandStartStacks((prev) => {
      let changed = false;
      const next = { ...prev };
      gameState.players.forEach((player) => {
        if (!Number.isFinite(next[player.sid])) {
          next[player.sid] = Number(player.chips ?? 0) + Number(player.current_bet ?? 0);
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [clearLog, gameState, getAvatarForSid, loadActionHistoryForHand, loadChatHistoryForHand, resetHistory, handStartHand, handStartStacks]);

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

  React.useEffect(() => {
    // Prevent stale cross-table state from rendering while new snapshot loads.
    reset();
    setLoadStatus('loading');
    prevHandRef.current = null;
    prevPlayerStatusRef.current = {};
    actionSeenRef.current = new Set();
    chatSeenRef.current = new Set();
    lastEventIdRef.current = null;
    lastChatIdRef.current = null;
    backfillEventsRef.current = false;
    backfillChatRef.current = false;
    initialEventsRef.current = false;
    initialChatRef.current = false;
    setActionItems([]);
    setChatItems([]);
    setActionPhaseCollapse({});
    setChatPhaseCollapse({});
    setSeatAnchors({});
    setPotAnchor(null);
    setSettlementPulse(null);
    setVictoryBanner(null);
  }, [tableId, reset]);

  const applyPhaseChange = React.useCallback((event: TexasEvent) => {
    const envelope = event?.event_type ? event : null;
    const inner = envelope?.payload ?? event;
    const payload = (inner?.payload || {}) as NonNullable<TexasEvent['payload']>;
    if (envelope?.id) trackLastEventId(envelope.id);
    const current = useTexasStore.getState().gameState;
    if (!current) return;
    const nextHand = Number(payload.hand_index);
    const currentHand = current.hand_number;
    if (Number.isFinite(nextHand) && Number.isFinite(currentHand) && nextHand < Number(currentHand)) {
      return;
    }
    if (Number.isFinite(nextHand) && Number.isFinite(currentHand) && nextHand > Number(currentHand)) {
      resetHistory();
    }
    const stacks = payload.stacks || {};
    const bets = payload.bets || {};
    const updatedPlayers = current.players.map((player) => {
      const id = Number(player.sid);
      const chips = Number(stacks[id] ?? player.chips);
      const currentBet = Number(bets[id] ?? player.current_bet ?? 0);
      return {
        ...player,
        chips,
        current_bet: currentBet,
      };
    });
    const currentBet = Math.max(0, ...Object.values(bets).map((value) => Number(value)));
    const shouldClearWinners = Number.isFinite(nextHand) && Number.isFinite(currentHand) && nextHand > Number(currentHand);
    setGameState({
      ...current,
      phase: payload.phase || current.phase,
      pot: payload.pot ?? current.pot,
      community_cards: (payload.board as string[]) || current.community_cards,
      current_bet: Number.isFinite(currentBet) ? currentBet : current.current_bet,
      current_player: payload.actor_id ? String(payload.actor_id) : current.current_player,
      hand_number: payload.hand_index ?? current.hand_number,
      timers: (payload.timers as Record<string, number> | undefined) ?? current.timers,
      winners: Array.isArray(payload.winner_ids)
        ? payload.winner_ids.map((id: string | number) => String(id))
        : (payload.winner_id ? [String(payload.winner_id)] : (shouldClearWinners ? [] : current.winners)),
      players: updatedPlayers,
    });
  }, [resetHistory, setGameState, trackLastEventId]);

  const handleHandResult = React.useCallback((event: TexasEvent) => {
    const envelope = event?.event_type ? event : null;
    const inner = envelope?.payload ?? event;
    const payload = (inner?.payload || inner || {}) as NonNullable<TexasEvent['payload']>;
    if (envelope?.id) trackLastEventId(envelope.id);
    const actionId = envelope?.action_id || inner?.action_id;
    const eventId = envelope?.event_id || inner?.event_id;
    const streamId = envelope?.id;
    const tsMs = envelope?.ts_ms ?? inner?.ts_ms;
    const currentHand = useTexasStore.getState().gameState?.hand_number;
    const handIndex = Number(payload?.hand_index ?? inner?.hand_index ?? currentHand ?? 0);
    if (Number.isFinite(handIndex) && Number.isFinite(currentHand) && Number(handIndex) < Number(currentHand)) {
      return;
    }
    if (Number.isFinite(handIndex)) {
      appendActionItem('hand_result', inner, Number(handIndex), {
        actionId: actionId ? String(actionId) : undefined,
        eventId: eventId ? String(eventId) : undefined,
        streamId: streamId ? String(streamId) : undefined,
        tsMs: tsMs as number | undefined,
      });
    }
    const payouts = payload?.payouts || {};
    const winners = Array.isArray(payload.winner_ids)
      ? payload.winner_ids.map((id: string | number) => String(id))
      : Object.keys(payouts);
    if (!winners || winners.length === 0) return;
    const current = useTexasStore.getState().gameState;
    if (current) {
      setGameState({ ...current, winners });
    }

    setSettlementPulse({ id: `${Date.now()}`, payouts });
  }, [appendActionItem, setGameState, trackLastEventId]);

  const handleSettlement = React.useCallback((event: TexasEvent) => {
    const envelope = event?.event_type ? event : null;
    const payload = (envelope?.payload ?? event) as TexasEvent;
    if (envelope?.id) trackLastEventId(envelope.id);
    const actionId = envelope?.action_id || payload?.action_id;
    const eventId = envelope?.event_id || payload?.event_id;
    const streamId = envelope?.id;
    const tsMs = envelope?.ts_ms ?? payload?.ts_ms;
    const currentHand = useTexasStore.getState().gameState?.hand_number;
    const handIndex = Number(payload?.hand_index ?? payload?.payload?.hand_index ?? currentHand ?? 0);
    if (Number.isFinite(handIndex) && Number.isFinite(currentHand) && Number(handIndex) < Number(currentHand)) {
      return;
    }
    if (Number.isFinite(handIndex)) {
      appendActionItem('settlement', payload, Number(handIndex), {
        actionId: actionId ? String(actionId) : undefined,
        eventId: eventId ? String(eventId) : undefined,
        streamId: streamId ? String(streamId) : undefined,
        tsMs: tsMs as number | undefined,
      });
    }
    const payouts = payload?.payouts || {};
    const winners = Object.keys(payouts).length > 0 ? Object.keys(payouts) : undefined;
    if (winners) {
      const current = useTexasStore.getState().gameState;
      if (current) {
        setGameState({ ...current, winners });
      }
      const topWinner = winners[0];
      const topAmount = payouts[topWinner];
      const winnerName = getAvatarForSid(String(topWinner));
      const message = winners.length > 1
        ? `WINNERS: ${winners.map((id) => getAvatarForSid(String(id))).join(' · ')}`
        : `WINNER: ${winnerName}${topAmount !== undefined ? ` +${topAmount}` : ''}`;
      setVictoryBanner({ id: `${Date.now()}`, message, winners });
      setSettlementPulse({ id: `${Date.now()}`, payouts });
    }
    setLoadStatus('ended');
  }, [appendActionItem, getAvatarForSid, setGameState, trackLastEventId]);

  const logTexasAction = React.useCallback((actionLabel: string, event: TexasEvent) => {
    const envelope = event?.event_type ? event : null;
    const inner = envelope?.payload ?? event;
    const payload = (inner?.payload || {}) as TexasEvent['payload'];
    if (envelope?.id) trackLastEventId(envelope.id);
    const actorId = inner?.actor_id ? String(inner.actor_id) : '';
    const nextActorId = inner?.next_actor_id ?? payload?.next_actor_id;
    const amount = payload?.amount;
    const msg = payload?.msg;
    const actorName = getAvatarForSid(actorId);
    const parts = [`🎲 ${actorName} ${actionLabel}`];
    if (amount !== undefined) parts.push(String(amount));
    if (msg) parts.push(`(${msg})`);
    addLog(parts.join(' '));
    const shouldTicker = ['raise', 'all-in', 'all_in'].includes(actionLabel);
    if (shouldTicker) {
      const label = `${actorName} ${actionLabel.toUpperCase()}${amount !== undefined ? ` ${amount}` : ''}`;
      setTicker({ message: label, tone: 'action' });
    }
    if (actorId) {
      setActiveSpeakerSid(actorId);
      if (activeSpeakerTimer.current) clearTimeout(activeSpeakerTimer.current);
      activeSpeakerTimer.current = setTimeout(() => setActiveSpeakerSid(undefined), 1800);
      setLastActionSid(actorId);
      if (lastActionTimer.current) clearTimeout(lastActionTimer.current);
      lastActionTimer.current = setTimeout(() => setLastActionSid(undefined), 2000);
    }
    const handIndex = Number(payload?.hand_index ?? inner?.hand_index);
    const currentHand = useTexasStore.getState().gameState?.hand_number;
    if (nextActorId !== undefined && nextActorId !== null) {
      const inCurrentHand = !Number.isFinite(handIndex) || !Number.isFinite(currentHand) || handIndex === Number(currentHand);
      if (inCurrentHand) {
        const current = useTexasStore.getState().gameState;
        if (current) {
          const nextId = String(nextActorId);
          if (current.current_player !== nextId) {
            setGameState({ ...current, current_player: nextId });
          }
        }
      }
    }
    if (!Number.isFinite(handIndex)) {
      return;
    }
    if (Number.isFinite(currentHand) && handIndex !== Number(currentHand)) {
      return;
    }
    const eventId = envelope?.event_id || inner?.event_id;
    const actionId = envelope?.action_id || inner?.action_id;
    const streamId = envelope?.id;
    const tsMs = envelope?.ts_ms ?? inner?.ts_ms;
    appendActionItem(actionLabel, inner, handIndex, {
      eventId: eventId ? String(eventId) : undefined,
      actionId: actionId ? String(actionId) : undefined,
      streamId: streamId ? String(streamId) : undefined,
      tsMs: tsMs as number | undefined
    });
    applyLocalAction(actionLabel, inner);
    requestRoomState();
  }, [addLog, appendActionItem, applyLocalAction, getAvatarForSid, requestRoomState, setGameState, trackLastEventId]);

  const logTexasChat = React.useCallback((data: TexasEvent) => {
    const envelope = data?.event_type ? data : null;
    const inner = (envelope?.payload ?? data) as TexasEvent;
    if (envelope?.id) trackLastChatId(envelope.id);
    const senderId = inner?.sender_id ?? inner?.actor_id ?? inner?.sender_name ?? inner?.actor_name;
    const sender = getAvatarForSid(senderId ? String(senderId) : undefined);
    const content = inner?.content || inner?.msg;
    if (!content) return;
    addLog(`💬 ${sender}: ${content}`);
    const handIndex = Number(inner?.meta?.hand_index ?? inner?.hand_index);
    const currentHand = useTexasStore.getState().gameState?.hand_number;
    if (!Number.isFinite(handIndex)) {
      return;
    }
    if (Number.isFinite(currentHand) && handIndex !== Number(currentHand)) {
      return;
    }
    const eventId = envelope?.event_id || inner?.event_id;
    const actionId = envelope?.action_id || inner?.action_id;
    const streamId = envelope?.id || inner?.id;
    const tsMs = envelope?.ts_ms ?? inner?.ts_ms;
    appendChatEntry(
      {
        id: eventId ? String(eventId) : (inner?.chat_id || inner?.id),
        action_id: actionId ? String(actionId) : undefined,
        stream_id: streamId ? String(streamId) : undefined,
        phase: inner?.meta?.phase ?? inner?.phase ?? undefined,
        sender_id: inner?.sender_id ?? inner?.actor_id ?? inner?.sender_name ?? null,
        content,
        ts_ms: tsMs as number | undefined,
      },
      handIndex
    );
  }, [addLog, appendChatEntry, getAvatarForSid, trackLastChatId]);

  const seedRecentEvents = React.useCallback((items: TexasEvent[] | null | undefined) => {
    if (!Array.isArray(items) || items.length === 0) return;
    const currentHand = useTexasStore.getState().gameState?.hand_number;
    items.forEach((envelope) => {
      if (envelope?.event_type === 'tx:phase:change') {
        applyPhaseChange(envelope);
        return;
      }
      if (envelope?.event_type === 'tx:hand:result') {
        handleHandResult(envelope);
        return;
      }
      if (envelope?.event_type === 'tx:settlement') {
        handleSettlement(envelope);
        return;
      }
      const eventType = envelope?.event_type;
      if (!eventType) return;
      const actionLabel = EVENT_ACTION_LABELS[eventType];
      if (!actionLabel) return;
      const inner = (envelope?.payload ?? envelope) as TexasEvent;
      const payload = (inner?.payload || {}) as NonNullable<TexasEvent['payload']>;
      const handIndex = Number(payload?.hand_index ?? inner?.hand_index ?? inner?.meta?.hand_index);
      const isSystem = SYSTEM_ACTIONS.has(actionLabel);
      if (!Number.isFinite(handIndex) && !isSystem) {
        return;
      }
      if (Number.isFinite(currentHand) && Number.isFinite(handIndex) && handIndex !== Number(currentHand)) {
        return;
      }
      const resolvedHand = Number.isFinite(handIndex) ? Number(handIndex) : Number(currentHand ?? 0);
      const eventId = envelope?.event_id || inner?.event_id;
      const actionId = envelope?.action_id || inner?.action_id;
      const streamId = envelope?.id;
      const tsMs = envelope?.ts_ms ?? inner?.ts_ms;
      appendActionItem(actionLabel, inner, resolvedHand, {
        eventId: eventId ? String(eventId) : undefined,
        actionId: actionId ? String(actionId) : undefined,
        streamId: streamId ? String(streamId) : undefined,
        tsMs,
      });
      if (streamId) trackLastEventId(String(streamId));
    });
  }, [EVENT_ACTION_LABELS, SYSTEM_ACTIONS, appendActionItem, applyPhaseChange, handleHandResult, handleSettlement, trackLastEventId]);

  const seedRecentChat = React.useCallback((items: TexasEvent[] | null | undefined) => {
    if (!Array.isArray(items) || items.length === 0) return;
    items.forEach((entry) => {
      const handIndex = Number(entry?.hand_index ?? entry?.meta?.hand_index);
      if (!Number.isFinite(handIndex)) {
        return;
      }
      appendChatEntry(
        {
          id: entry?.event_id || entry?.id,
          action_id: entry?.action_id ?? undefined,
          stream_id: entry?.id,
          phase: entry?.phase ?? entry?.meta?.phase ?? undefined,
          sender_id: entry?.sender_id ?? entry?.sender_name ?? null,
          content: entry?.content ?? '',
          ts_ms: entry?.ts_ms,
        },
        Number(handIndex)
      );
      if (entry?.id) trackLastChatId(String(entry.id));
    });
  }, [appendChatEntry, trackLastChatId]);

  const backfillRoomEvents = React.useCallback(async (handNumber: number) => {
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
        tableId,
        100,
        undefined,
        initial ? undefined : afterId,
        TEXAS_EVENT_TYPES
      );
      const items = history.items || [];
      items.forEach((item) => {
        if (item.event_type === 'tx:phase:change') {
          applyPhaseChange(item as TexasEvent);
          if (item.id) trackLastEventId(item.id);
          return;
        }
        if (item.event_type === 'tx:hand:result') {
          handleHandResult(item as TexasEvent);
          if (item.id) trackLastEventId(item.id);
          return;
        }
        if (item.event_type === 'tx:settlement') {
          handleSettlement(item as TexasEvent);
          if (item.id) trackLastEventId(item.id);
          return;
        }
        const actionLabel = EVENT_ACTION_LABELS[item.event_type];
        if (!actionLabel) return;
        const event = (item.payload || {}) as TexasEvent;
        const eventHand = Number(event?.payload?.hand_index ?? event?.hand_index ?? event?.meta?.hand_index);
        const isSystem = SYSTEM_ACTIONS.has(actionLabel);
        if (!Number.isFinite(eventHand) && !isSystem) {
          return;
        }
        if (Number.isFinite(handNumber) && Number.isFinite(eventHand) && eventHand !== handNumber) {
          return;
        }
        const resolvedHand = Number.isFinite(eventHand) ? Number(eventHand) : handNumber;
        appendActionItem(actionLabel, event, resolvedHand, {
          eventId: item.event_id ?? undefined,
          actionId: item.action_id ?? undefined,
          streamId: item.id,
          tsMs: item.ts_ms,
        });
        trackLastEventId(item.id);
      });
      if (history.last_id) lastEventIdRef.current = history.last_id;
    } catch {
    } finally {
      backfillEventsRef.current = false;
    }
  }, [EVENT_ACTION_LABELS, SYSTEM_ACTIONS, TEXAS_EVENT_TYPES, appendActionItem, applyPhaseChange, handleHandResult, handleSettlement, tableId, trackLastEventId]);

  const backfillRoomChat = React.useCallback(async (handNumber: number) => {
    if (backfillChatRef.current) return;
    const afterId = lastChatIdRef.current;
    const initial = !afterId;
    if (initial) {
      if (initialChatRef.current) return;
      initialChatRef.current = true;
    }
    backfillChatRef.current = true;
    try {
      const history = await fetchRoomChatHistory(
        tableId,
        100,
        undefined,
        initial ? undefined : afterId,
        handNumber
      );
      const items = history.items || [];
      items.forEach((msg) => {
        if (!Number.isFinite(Number(msg.hand_index))) {
          return;
        }
        appendChatEntry(
          {
            id: msg.event_id || msg.id,
            action_id: msg.action_id ?? undefined,
            stream_id: msg.id,
            phase: msg.phase ?? undefined,
            sender_id: msg.sender_id ?? msg.sender_name ?? null,
            content: msg.content,
            ts_ms: msg.ts_ms,
          },
          handNumber
        );
        trackLastChatId(msg.id);
      });
      if (history.last_id) lastChatIdRef.current = history.last_id;
    } catch {
    } finally {
      backfillChatRef.current = false;
    }
  }, [appendChatEntry, tableId, trackLastChatId]);

  useSpectatorSocket({
    namespace: 'texas',
    tableId,
    events: {
      'room:state': (data) => {
        const mapped = mapTexasRoomState(data);
        if (mapped) {
          setGameState(mapped);
          setLoadStatus('ready');
        }
        if (data?.last_event_id) lastEventIdRef.current = String(data.last_event_id);
        if (data?.last_chat_id) lastChatIdRef.current = String(data.last_chat_id);
        if (data?.recent_events) seedRecentEvents(data.recent_events as TexasEvent[]);
        if (data?.recent_chat) seedRecentChat(data.recent_chat as TexasEvent[]);
        const handNumber = Number(mapped?.hand_number ?? (data?.game_state as Record<string, unknown>)?.hand_index ?? 0);
        if (Number.isFinite(handNumber)) {
          backfillRoomEvents(handNumber);
          backfillRoomChat(handNumber);
        }
      },
      'room:update': (data) => {
        if (data?.id) trackLastEventId(String(data.id));
        if ((data?.payload as Record<string, unknown>)?.type === 'game_finish') {
          setLoadStatus('ended');
        }
      },
      'tx:phase:change': applyPhaseChange,
      'tx:hand:result': handleHandResult,
      'tx:bet': (data) => logTexasAction('bet', data),
      'tx:call': (data) => logTexasAction('call', data),
      'tx:raise': (data) => logTexasAction('raise', data),
      'tx:check': (data) => logTexasAction('check', data),
      'tx:fold': (data) => logTexasAction('fold', data),
      'tx:all_in': (data) => logTexasAction('all-in', data),
      'tx:vote_end': (data) => logTexasAction('vote_end', data),
      'room:chat': (data) => {
        console.log('[Texas] room:chat', data);
        logTexasChat(data);
      },
      'tx:settlement': handleSettlement,
      connect: () => {
        setConnected(true);
        setHasConnectedOnce(true);
      },
      disconnect: () => setConnected(false),
    }
  });

  React.useEffect(() => {
    const handNumber = Number(gameState?.hand_number ?? 0);
    if (!Number.isFinite(handNumber)) return;
    const tick = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      backfillRoomEvents(handNumber);
      backfillRoomChat(handNumber);
    };
    const interval = setInterval(tick, BACKFILL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [backfillRoomChat, backfillRoomEvents, gameState?.hand_number]);

  React.useEffect(() => {
    const timeout = setTimeout(() => {
      if (!useTexasStore.getState().gameState) {
        setLoadStatus('error');
      }
    }, 8000);
    return () => clearTimeout(timeout);
  }, []);

  const isTerminalTable = gameState?.phase === 'finished';

  React.useEffect(() => {
    if (!gameState) return;
    if (prevPhase.current && prevPhase.current !== gameState.phase) {
      addLog(`🕒 Phase: ${gameState.phase.replace(/_/g, ' ')}`);
      if (process.env.NODE_ENV === 'development') {
        console.log('[Texas] phase change', {
          phase: gameState.phase,
          handNumber: gameState.hand_number,
          board: gameState.community_cards,
        });
      }
    }
    prevPhase.current = gameState.phase;
    if (gameState.current_player && prevCurrentPlayer.current !== gameState.current_player) {
      const current = gameState.players.find((p) => p.sid === gameState.current_player);
      addLog(`🎯 Turn: ${getAvatarForSid(current?.sid || gameState.current_player)}`);
      prevCurrentPlayer.current = gameState.current_player;
      if (activeSpeakerSid && activeSpeakerSid !== gameState.current_player) {
        setActiveSpeakerSid(undefined);
      }
      if (lastActionSid && lastActionSid !== gameState.current_player) {
        setLastActionSid(undefined);
      }
    }
  }, [activeSpeakerSid, addLog, gameState, getAvatarForSid, lastActionSid]);

  const paidMap = React.useMemo(() => {
    if (handStartHand === null || handStartHand !== (gameState?.hand_number ?? null)) {
      return {};
    }
    const map: Record<string, number> = {};
    const players = gameState?.players ?? [];
    players.forEach((player) => {
      const start = Number(handStartStacks[player.sid] ?? player.chips ?? 0);
      const now = Number(player.chips ?? 0);
      map[player.sid] = Math.max(0, start - now);
    });
    return map;
  }, [gameState?.hand_number, gameState?.players, handStartHand, handStartStacks]);
  const totalBets = React.useMemo(() => {
    const players = gameState?.players ?? [];
    return players.reduce((sum, player) => sum + Number(player.current_bet ?? 0), 0);
  }, [gameState?.players]);
  const displayPot = Math.max(0, Number(gameState?.pot ?? 0) + totalBets);
  const stageWidth = stageSize.width || BASE_STAGE_WIDTH;
  const stageHeight = stageSize.height || BASE_STAGE_HEIGHT;
  const stageScale = React.useMemo(
    () => Math.min(1, stageWidth / BASE_STAGE_WIDTH, stageHeight / BASE_STAGE_HEIGHT),
    [stageWidth, stageHeight]
  );

  const persistElementOffsets = React.useCallback(async (nextOffsets: Record<string, { x: number; y: number }>) => {
    try {
      const res = await fetch('/api/texas-seat-layout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ elementOffsets: nextOffsets })
      });
      if (!res.ok) return;
      const data = await res.json();
      if (data) {
        setLayoutConfig(data);
      }
    } catch {
    }
  }, [setLayoutConfig]);

  const handleWinnerPointerDown = React.useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!debugSeatLayout) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.currentTarget?.setPointerCapture) {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    winnerDragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      originX: winnerOffset.x,
      originY: winnerOffset.y
    };
  }, [debugSeatLayout, winnerOffset.x, winnerOffset.y]);

  React.useEffect(() => {
    if (!debugSeatLayout) return;
    const handleMove = (event: PointerEvent) => {
      const drag = winnerDragRef.current;
      if (!drag) return;
      const scale = stageScale || 1;
      const dx = (event.clientX - drag.startX) / (scale || 1);
      const dy = (event.clientY - drag.startY) / (scale || 1);
      setLayoutConfig((prev: SeatLayoutConfig) => {
        const base = prev || {};
        const nextOffsets = { ...(base.elementOffsets || {}) };
        nextOffsets.winner = { x: drag.originX + dx, y: drag.originY + dy };
        return { ...base, elementOffsets: nextOffsets };
      });
    };
    const handleUp = (event: PointerEvent) => {
      const drag = winnerDragRef.current;
      if (!drag) return;
      winnerDragRef.current = null;
      const scale = stageScale || 1;
      const dx = (event.clientX - drag.startX) / (scale || 1);
      const dy = (event.clientY - drag.startY) / (scale || 1);
      const baseOffsets = layoutConfigRef.current?.elementOffsets || {};
      const nextOffsets = { ...baseOffsets, winner: { x: drag.originX + dx, y: drag.originY + dy } };
      setLayoutConfig((prev: SeatLayoutConfig) => ({ ...(prev || {}), elementOffsets: nextOffsets }));
      void persistElementOffsets(nextOffsets);
    };
    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', handleUp);
    return () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', handleUp);
    };
  }, [debugSeatLayout, persistElementOffsets, stageScale, setLayoutConfig]);

  const toStagePoint = React.useCallback((rect: DOMRect | null) => {
    if (!rect) return null;
    const frame = stageFrameRef.current;
    if (!frame) return null;
    const frameRect = frame.getBoundingClientRect();
    const scale = stageScale || 1;
    if (!Number.isFinite(scale) || scale <= 0) return null;
    return {
      x: (rect.left + rect.width / 2 - frameRect.left) / scale,
      y: (rect.top + rect.height / 2 - frameRect.top) / scale
    };
  }, [stageScale]);

  const handleSeatAnchor = React.useCallback((sid: string, rect: DOMRect) => {
    const point = toStagePoint(rect);
    if (!point) return;
    setSeatAnchors((prev) => {
      const prior = prev[sid];
      if (prior && Math.abs(prior.x - point.x) < 0.5 && Math.abs(prior.y - point.y) < 0.5) {
        return prev;
      }
      return { ...prev, [sid]: point };
    });
  }, [toStagePoint]);

  React.useLayoutEffect(() => {
    const rect = potRef.current?.getBoundingClientRect() ?? null;
    const point = toStagePoint(rect);
    if (point) {
      setPotAnchor(point);
    }
  }, [toStagePoint, stageWidth, stageHeight, stageScale, displayPot]);

  React.useEffect(() => {
    if (!victoryBanner) return;
    const timeout = setTimeout(() => setVictoryBanner(null), VICTORY_DURATION_MS);
    return () => clearTimeout(timeout);
  }, [victoryBanner]);

  if (isTerminalTable) {
    return (
      <div className={`min-h-screen flex items-center justify-center font-mono ${
        isAgent ? 'bg-black text-green-500' : 'bg-slate-50 text-slate-500'
      }`}>
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="text-4xl">🏁</div>
          <div className="text-lg font-semibold">This game has ended.</div>
          <div className="text-xs opacity-70">Return to the lobby to watch active tables.</div>
        </div>
      </div>
    );
  }

  if (!gameState) {
    if (loadStatus === 'ended') {
      return (
        <div className={`min-h-screen flex items-center justify-center font-mono ${
          isAgent ? 'bg-black text-green-500' : 'bg-slate-50 text-slate-500'
        }`}>
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="text-4xl">🏁</div>
            <div className="text-lg font-semibold">This game has ended.</div>
            <div className="text-xs opacity-70">Return to the lobby to watch active tables.</div>
          </div>
        </div>
      );
    }

    if (loadStatus === 'error') {
      return (
        <div className={`min-h-screen flex items-center justify-center font-mono ${
          isAgent ? 'bg-black text-green-500' : 'bg-slate-50 text-slate-500'
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
        isAgent ? 'bg-black text-green-500' : 'bg-slate-50 text-slate-500'
      }`}>
        <div className="animate-pulse flex flex-col items-center gap-4">
          {isAgent ? (
            <>
              <div className="text-4xl">🦞</div>
              <div>CONNECTING TO SATELLITE...</div>
            </>
          ) : (
            <>
              <div className="w-12 h-12 border-4 border-slate-200 border-t-blue-500 rounded-full animate-spin"></div>
              <div>Loading table...</div>
            </>
          )}
        </div>
      </div>
    );
  }

  const totalPlayers = gameState.players.length;
  const dealerIndex = Number.isFinite(gameState.dealer_position) ? Number(gameState.dealer_position) : undefined;
  const smallBlindIndex = Number.isFinite(gameState.sb_position) 
    ? Number(gameState.sb_position) 
    : (dealerIndex !== undefined && totalPlayers > 0 ? (dealerIndex + 1) % totalPlayers : undefined);
  const bigBlindIndex = Number.isFinite(gameState.bb_position)
    ? Number(gameState.bb_position)
    : (dealerIndex !== undefined && totalPlayers > 0 ? (dealerIndex + 2) % totalPlayers : undefined);
  const winnerSet = new Set(gameState.winners ?? []);
  const scale = stageScale;
  const tableCenter: AnchoredCenter = {
    percent: { left: '50%', top: '50%' },
    pixel: { x: BASE_STAGE_WIDTH / 2, y: BASE_STAGE_HEIGHT / 2 },
    stageSize: { width: BASE_STAGE_WIDTH, height: BASE_STAGE_HEIGHT }
  };
  const currentHandIndex = Number(gameState.hand_number ?? 0);
  const visibleActionItems = actionItems.filter((item) => item.handIndex === currentHandIndex);
  const visibleChatItems = chatItems.filter((item) => item.handIndex === currentHandIndex);
  const actionCount = visibleActionItems.filter((item) => item.kind === 'action').length;
  const chatCount = visibleChatItems.filter((item) => item.kind === 'chat').length;
  const phaseRank: Record<string, number> = {
    preflop: 0,
    flop: 1,
    turn: 2,
    river: 3,
    showdown: 4,
    finished: 5,
  };
  const currentPhaseKey = normalizePhase(gameState.phase) || 'unknown';
  const isLatePhase = (phase: string) => phase === 'showdown' || phase === 'finished';
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
  const buildPhaseGroups = <T extends { phase?: string; ts_ms?: number; stream_id?: string }>(items: T[]) => {
    const groups = new Map<string, T[]>();
    items.forEach((item) => {
      const phase = normalizePhase(item.phase) || currentPhaseKey;
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
  const actionPhaseGroups = buildPhaseGroups(visibleActionItems);
  const chatPhaseGroups = buildPhaseGroups(visibleChatItems);
  const handLabel = `HAND ${Math.max(1, (gameState.hand_number ?? 0) + 1)}`;
  const phaseLabel = (gameState.phase || 'unknown').replace(/_/g, ' ').toUpperCase();
  return (
    <div className={`flex h-screen overflow-hidden font-mono transition-colors duration-500 ${
      isAgent ? 'bg-[#0a0a0a] text-emerald-100' : 'bg-slate-50 text-sky-900'
    }`}>
      {!isConnected && hasConnectedOnce && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[70] pointer-events-none">
          <div className={`px-4 py-2 rounded-full border text-xs font-semibold tracking-wide ${
            isAgent
              ? 'bg-amber-900/70 border-amber-400/40 text-amber-100'
              : 'bg-amber-50 border-amber-200 text-amber-800'
          }`}>
            Connection lost. Reconnecting automatically...
          </div>
        </div>
      )}
      {/* Left Actions Panel */}
      <div
        className={`w-64 border-r px-4 py-4 overflow-x-hidden ${
          isAgent ? 'border-emerald-500/20 bg-black/60 text-emerald-100' : 'border-sky-200/80 bg-sky-50/80 text-sky-800'
        }`}
        style={{ transform: `translate(${getElementOffset('actionPanel').x}px, ${getElementOffset('actionPanel').y}px)` }}
      >
        <div className="text-[13px] font-bold uppercase tracking-[0.32em] opacity-80">Actions ({actionCount})</div>
        <div className={`mt-2 text-[11px] font-semibold uppercase tracking-[0.3em] ${
          isAgent ? 'text-emerald-200/70' : 'text-sky-600/70'
        }`}>
          {handLabel} · {phaseLabel}
        </div>
        <div className="mt-3 space-y-2 text-sm max-h-[calc(100vh-220px)] overflow-y-auto pr-1 overflow-x-hidden">
          {actionCount === 0 ? (
            <div className="opacity-70">No key actions yet.</div>
          ) : (
            actionPhaseGroups.map((group) => {
              const isCurrent = group.phase === currentPhaseKey;
              const collapsed = actionPhaseCollapse[group.phase] ?? !isCurrent;
              return (
                <div key={`action-phase-${group.phase}`} className="space-y-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (isCurrent) return;
                      setActionPhaseCollapse((prev) => ({
                        ...prev,
                        [group.phase]: !(prev[group.phase] ?? true),
                      }));
                    }}
                    className={`w-full flex items-center justify-between text-[11px] font-bold uppercase tracking-[0.3em] ${
                      isCurrent
                        ? (isAgent ? 'text-emerald-200' : 'text-sky-800')
                        : (isAgent ? 'text-emerald-200/70' : 'text-sky-700/70')
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span>{formatPhase(group.phase)}</span>
                      {isCurrent ? (
                        <span className={`text-[9px] px-2 py-0.5 rounded-full border ${
                          isAgent ? 'border-emerald-400/40' : 'border-sky-400/40'
                        }`}>LIVE</span>
                      ) : (
                        <span className={`text-[9px] px-2 py-0.5 rounded-full border opacity-70 ${
                          isAgent ? 'border-emerald-400/20' : 'border-sky-400/20'
                        }`}>PAST</span>
                      )}
                    </span>
                    {!isCurrent && (
                      <span className="text-[10px] flex items-center gap-2 opacity-70">
                        <span>{collapsed ? 'SHOW' : 'HIDE'}</span>
                        <span>{collapsed ? '▸' : '▾'}</span>
                      </span>
                    )}
                  </button>
                  {!collapsed && (
                    group.items.length === 0 ? (
                      <div className="opacity-60 text-xs">No actions yet.</div>
                    ) : (
                      group.items.map((item, idx) => {
                        const lower = item.action.toLowerCase();
                        const isKey = lower.includes('all-in') || lower.includes('all in') || lower.includes('raise') || lower.includes('showdown') || lower.includes('wins');
                        const icon = lower.includes('all-in') || lower.includes('all in')
                          ? '💥'
                          : lower.includes('raise')
                            ? '🚀'
                            : lower.includes('bet')
                              ? '🪙'
                              : lower.includes('call')
                                ? '📞'
                                : lower.includes('check')
                                  ? '✅'
                                  : lower.includes('fold')
                                    ? '🪫'
                                    : lower.includes('hand_result')
                                      ? '🏆'
                                      : lower.includes('settlement')
                                        ? '🏁'
                                        : '🎲';
                        const isLatest = isCurrent && idx === 0;
                        const isActing = isLatest;
                        return (
                          <div
                            key={item.id}
                            className={`leading-snug flex items-start gap-2 ${
                              isActing
                                ? (isAgent ? 'text-emerald-100 font-extrabold' : 'text-sky-900 font-bold')
                                : isLatest
                                  ? (isAgent ? 'text-emerald-100 font-semibold' : 'text-sky-800 font-semibold')
                                  : isKey
                                    ? (isAgent ? 'text-emerald-200 font-semibold' : 'text-sky-700 font-semibold')
                                    : (isAgent ? 'text-emerald-200/70' : 'text-sky-700/80')
                            }`}
                          >
                            <span className="text-base">{isActing ? '▶︎' : icon}</span>
                            <span>{item.message}</span>
                          </div>
                        );
                      })
                    )
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Main Game Area */}
      <div ref={stageContainerRef} className={`flex-1 relative overflow-hidden ${
        isAgent 
          ? 'bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-green-900/20 via-black to-black'
          : 'bg-slate-100'
      }`}>
        {debugSeatLayout && (
          <div className="absolute top-4 left-4 z-40 flex items-center gap-2">
            <button
              type="button"
              onClick={exportSeatLayout}
              className={`px-3 py-1.5 rounded-full text-[11px] font-bold tracking-wide border ${
                isAgent
                  ? 'bg-black/70 border-emerald-400/40 text-emerald-200 hover:border-emerald-300/70 hover:text-emerald-100'
                  : 'bg-white/90 border-sky-200 text-sky-700 hover:border-sky-300'
              }`}
            >
              Export Seat Layout
            </button>
            <button
              type="button"
              onClick={clearSeatLayout}
              className={`px-3 py-1.5 rounded-full text-[11px] font-bold tracking-wide border ${
                isAgent
                  ? 'bg-black/60 border-rose-400/40 text-rose-200 hover:border-rose-300/70 hover:text-rose-100'
                  : 'bg-white/90 border-rose-200 text-rose-700 hover:border-rose-300'
              }`}
            >
              Clear Local Layout
            </button>
          </div>
        )}
          <div className={`absolute bottom-10 left-1/2 -translate-x-1/2 px-4 py-1 rounded-full border text-[12px] font-semibold tracking-wide ${
            isAgent
              ? 'bg-black/60 border-emerald-400/20 text-emerald-200'
            : 'bg-sky-50/80 border-sky-200 text-sky-800'
        }`}>
          D = Dealer · SB = Small Blind · BB = Big Blind
        </div>
        <div
          ref={stageFrameRef}
          className="absolute left-1/2 top-1/2"
          style={{
            left: `calc(50% + ${TABLE_SHIFT_X}px)`,
            width: BASE_STAGE_WIDTH,
            height: BASE_STAGE_HEIGHT,
            transform: `translate(-50%, -50%) scale(${scale})`,
            transformOrigin: 'center center'
          }}
        >
          {/* Table Felt */}
          <div className={`absolute inset-4 m-auto w-[82%] h-[72%] border-[18px] rounded-[220px] shadow-2xl relative ${
            isAgent
              ? 'border-emerald-900/60 bg-[#0f2a15] shadow-[inset_0_0_100px_rgba(0,0,0,0.8)]'
              : 'border-sky-200/80 bg-sky-400/60 shadow-[inset_0_0_50px_rgba(0,0,0,0.08)]'
          }`}>
            <div
              className="absolute left-1/2 top-1.5 z-30 pointer-events-none"
              style={{ transform: `translate(-50%, 0) translate(${getElementOffset('round').x}px, ${getElementOffset('round').y}px)` }}
            >
              <div className={`px-5 py-2 rounded-full text-sm font-bold tracking-wide border ${
                isAgent
                  ? 'bg-black/70 border-emerald-400/40 text-emerald-100'
                  : 'bg-sky-50/90 border-sky-200 text-sky-800'
              }`}>
                Round {Math.max(1, (gameState.hand_number ?? 0) + 1)}: {(gameState.phase || 'unknown').replace(/_/g, ' ').toUpperCase()}
              </div>
            </div>
            <AnimatePresence>
              {victoryBanner && (
                <div
                  className={`absolute left-1/2 top-12 z-40 ${debugSeatLayout ? 'pointer-events-auto cursor-grab' : 'pointer-events-none'}`}
                  style={{ transform: `translate(-50%, 0) translate(${winnerOffset.x}px, ${winnerOffset.y}px)` }}
                  onPointerDown={handleWinnerPointerDown}
                >
                  <motion.div
                    key={victoryBanner.id}
                    initial={{ opacity: 0, y: -8, scale: 0.96 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -6, scale: 0.96 }}
                    transition={{ duration: 0.35 }}
                  >
                    <div className={`px-6 py-2 rounded-full border text-sm font-bold tracking-wide ${
                      isAgent
                        ? 'bg-amber-500/15 border-amber-300/60 text-amber-100 shadow-[0_0_24px_rgba(251,191,36,0.45)]'
                        : 'bg-sky-100 border-sky-200 text-sky-800 shadow-lg'
                    }`}>
                      {victoryBanner.message}
                    </div>
                  </motion.div>
                </div>
              )}
            </AnimatePresence>
            <CommunityCards cards={gameState.community_cards || []} center={tableCenter} offset={getElementOffset('communityCards')} />
            {/* BroadcastHud removed from center to reduce clutter */}
            <div
              className="absolute left-1/2 top-1/2 z-30 pointer-events-none"
              style={{ transform: `translate(-50%, -50%) translate(${getElementOffset('pot').x}px, ${getElementOffset('pot').y}px)` }}
            >
              <div
                ref={potRef}
                className={`px-5 py-2 rounded-full border text-sm font-bold tracking-wide ${
                isAgent
                  ? 'bg-black/75 border-emerald-400/40 text-emerald-100 shadow-[0_10px_30px_rgba(16,185,129,0.2)]'
                  : 'bg-white/95 border-sky-200 text-sky-800 shadow-lg'
              }`}
              >
                POT 🪙{displayPot}
              </div>
            </div>
            <div
              className={`absolute inset-0 flex items-center justify-center text-center pointer-events-none select-none z-0 ${
              isAgent ? 'text-green-900/30' : 'text-white/10'
            }`}
            >
              <div className="flex flex-col items-center justify-center">
                <div className="text-5xl md:text-6xl font-black tracking-tighter opacity-50">
                  CLAW<span className={isAgent ? 'text-green-800/40' : 'text-white/20'}>ARENA</span>.IO
                </div>
                <div className="text-6xl md:text-7xl mt-4 opacity-25 filter blur-[1px] w-fit mx-auto">🦞</div>
              </div>
            </div>
          </div>

          {/* Game Components */}
          <EventTicker message={ticker?.message} tone={ticker?.tone} />

          {/* Players */}
          {gameState.players.map((player, idx) => {
            const phase = String(gameState.phase || '').toLowerCase();
            const isBettingPhase = ['preflop', 'flop', 'turn', 'river'].includes(phase);
            const isTurnPlayer = isBettingPhase
              && gameState.current_player === player.sid
              && player.status === 'active';
            return (
            <PlayerSeat
              key={player.sid}
              player={player}
              index={idx}
              totalPlayers={gameState.players.length}
              center={tableCenter}
              paidTotal={paidMap[player.sid]}
              avatarOverride={SEAT_AVATARS[idx % SEAT_AVATARS.length]}
              debugLayout={debugSeatLayout}
              layoutNonce={layoutNonce}
              isAgent={isAgent}
              isDealer={dealerIndex === idx}
              isSmallBlind={smallBlindIndex === idx}
              isBigBlind={bigBlindIndex === idx}
              isCurrentTurn={isTurnPlayer}
              isSpeaking={isTurnPlayer && activeSpeakerSid === player.sid}
              isWinner={winnerSet.has(player.sid)}
              onAvatarAnchor={handleSeatAnchor}
            />
            );
          })}

          {/* Animations */}
            <ChipStream
              players={gameState.players}
              center={tableCenter}
              seatAnchors={seatAnchors}
              potAnchor={potAnchor}
              paidMap={paidMap}
              settlement={settlementPulse}
              handNumber={gameState.hand_number}
            />

        </div>
      </div>

      {/* Right Chat Panel */}
        <div
          className={`w-64 border-l px-4 py-4 overflow-x-hidden ${
            isAgent ? 'border-emerald-500/20 bg-black/60 text-emerald-100' : 'border-sky-200/80 bg-sky-50/80 text-sky-800'
          }`}
          style={{ transform: `translate(${getElementOffset('chatPanel').x}px, ${getElementOffset('chatPanel').y}px)` }}
        >
        <div className="text-[13px] font-bold uppercase tracking-[0.32em] opacity-80">Chat ({chatCount})</div>
        <div className={`mt-2 text-[11px] font-semibold uppercase tracking-[0.3em] ${
          isAgent ? 'text-emerald-200/70' : 'text-sky-600/70'
        }`}>
          {handLabel} · {phaseLabel}
        </div>
        <div className="mt-3 space-y-2 text-sm max-h-[calc(100vh-220px)] overflow-y-auto pr-1 overflow-x-hidden">
          {chatCount === 0 ? (
            <div className="opacity-70">No messages yet.</div>
          ) : (
            chatPhaseGroups.map((group) => {
              const isCurrent = group.phase === currentPhaseKey;
              const collapsed = chatPhaseCollapse[group.phase] ?? !isCurrent;
              return (
                <div key={`chat-phase-${group.phase}`} className="space-y-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (isCurrent) return;
                      setChatPhaseCollapse((prev) => ({
                        ...prev,
                        [group.phase]: !(prev[group.phase] ?? true),
                      }));
                    }}
                    className={`w-full flex items-center justify-between text-[11px] font-bold uppercase tracking-[0.3em] ${
                      isCurrent
                        ? (isAgent ? 'text-emerald-200' : 'text-sky-800')
                        : (isAgent ? 'text-emerald-200/70' : 'text-sky-700/70')
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span>{formatPhase(group.phase)}</span>
                      {isCurrent ? (
                        <span className={`text-[9px] px-2 py-0.5 rounded-full border ${
                          isAgent ? 'border-emerald-400/40' : 'border-sky-400/40'
                        }`}>LIVE</span>
                      ) : (
                        <span className={`text-[9px] px-2 py-0.5 rounded-full border opacity-70 ${
                          isAgent ? 'border-emerald-400/20' : 'border-sky-400/20'
                        }`}>PAST</span>
                      )}
                    </span>
                    {!isCurrent && (
                      <span className="text-[10px] flex items-center gap-2 opacity-70">
                        <span>{collapsed ? 'SHOW' : 'HIDE'}</span>
                        <span>{collapsed ? '▸' : '▾'}</span>
                      </span>
                    )}
                  </button>
                  {!collapsed && (
                    group.items.length === 0 ? (
                      <div className="opacity-60 text-xs">No messages yet.</div>
                    ) : (
                      group.items.map((item, idx) => {
                        const isLatest = isCurrent && idx === 0;
                        const isActing = isLatest;
                        return (
                          <div
                            key={item.id}
                            className={`leading-snug flex items-start gap-2 ${
                              isActing
                                ? (isAgent ? 'text-emerald-100 font-extrabold' : 'text-sky-900 font-bold')
                                : isLatest
                                  ? (isAgent ? 'text-emerald-100 font-semibold' : 'text-sky-800 font-semibold')
                                  : ''
                            }`}
                          >
                            <span className="text-base">{isActing ? '▶︎' : '💬'}</span>
                            <span>{item.message}</span>
                          </div>
                        );
                      })
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

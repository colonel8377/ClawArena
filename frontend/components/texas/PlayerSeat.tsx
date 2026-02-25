'use client';

import React from 'react';
import { SpectatorPlayer } from '@/store/types';
import PlayingCard from '../poker/PlayingCard'; 
import { parseCard } from '../poker/utils';
import { getSeatPosition } from './seatPositions';
import { motion } from 'framer-motion';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';
import AgentSummaryHover from '@/components/AgentSummaryHover';

interface PlayerSeatProps {
  player: SpectatorPlayer;
  index: number;
  totalPlayers: number;
  center: AnchoredCenter;
  positionOverride?: { x: number; y: number };
  onPointerDown?: (event: React.PointerEvent<HTMLDivElement>) => void;
  avatarOverride?: string;
  paidTotal?: number;
  debugLayout?: boolean;
  layoutNonce?: number;
  isAgent?: boolean;
  isDealer?: boolean;
  isSmallBlind?: boolean;
  isBigBlind?: boolean;
  isCurrentTurn?: boolean;
  isSpeaking?: boolean;
  isWinner?: boolean;
  onAvatarAnchor?: (sid: string, rect: DOMRect) => void;
}

export const SEAT_AVATARS = ['😺', '🐶', '🐵', '🦊', '🐸', '🐼', '🐻', '🐯', '🦁', '🐷', '🐨', '🐧', '🦄', '🐙', '🦉', '🐺', '🦍', '🦧'];

const hashString = (value: string) => {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
};

const formatChips = (value?: number) => (Number.isFinite(value) ? Number(value).toLocaleString() : '0');

export default function PlayerSeat({
  player,
  index,
  totalPlayers,
  center,
  positionOverride,
  onPointerDown,
  avatarOverride,
  paidTotal,
  debugLayout = false,
  layoutNonce = 0,
  isAgent = true,
  isDealer = false,
  isSmallBlind = false,
  isBigBlind = false,
  isCurrentTurn = false,
  isSpeaking = false,
  isWinner = false,
  onAvatarAnchor
}: PlayerSeatProps) {
  const storageKey = React.useMemo(() => `texas:seatLayout:${totalPlayers}`, [totalPlayers]);
  const [debugOffset, setDebugOffset] = React.useState({ x: 0, y: 0 });
  const debugOffsetRef = React.useRef({ x: 0, y: 0 });
  const dragRef = React.useRef<{ startX: number; startY: number; offsetX: number; offsetY: number } | null>(null);
  const avatarRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!debugLayout || typeof window === 'undefined') return;
    try {
      const raw = window.localStorage.getItem(storageKey);
      const parsed = raw ? JSON.parse(raw) : {};
      const saved = parsed?.[index];
      if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
        setDebugOffset(saved);
        debugOffsetRef.current = saved;
      } else {
        setDebugOffset({ x: 0, y: 0 });
        debugOffsetRef.current = { x: 0, y: 0 };
      }
    } catch {
      setDebugOffset({ x: 0, y: 0 });
      debugOffsetRef.current = { x: 0, y: 0 };
    }
  }, [debugLayout, storageKey, index, layoutNonce]);

  React.useEffect(() => {
    if (!debugLayout) return;
    const onMove = (event: PointerEvent) => {
      if (!dragRef.current) return;
      const dx = event.clientX - dragRef.current.startX;
      const dy = event.clientY - dragRef.current.startY;
      const next = { x: dragRef.current.offsetX + dx, y: dragRef.current.offsetY + dy };
      debugOffsetRef.current = next;
      setDebugOffset(next);
    };
    const onUp = () => {
      if (!dragRef.current) return;
      dragRef.current = null;
      try {
        const raw = window.localStorage.getItem(storageKey);
        const parsed = raw ? JSON.parse(raw) : {};
        parsed[index] = debugOffsetRef.current;
        window.localStorage.setItem(storageKey, JSON.stringify(parsed));
        console.log('[Texas SeatLayout] saved', { index, offset: debugOffsetRef.current, totalPlayers });
      } catch {
      }
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [debugLayout, index, storageKey, totalPlayers]);

  const offset = positionOverride ?? getSeatPosition(index, totalPlayers, center.stageSize);
  const baseX = Number.isFinite(center.pixel.x) ? center.pixel.x : center.stageSize.width / 2;
  const baseY = Number.isFinite(center.pixel.y) ? center.pixel.y : center.stageSize.height / 2;
  const bottomNudge = offset.y > 0 ? Math.min(38, offset.y * 0.15) : 0;
  const seatScale = totalPlayers >= 9 ? 0.88 : totalPlayers >= 7 ? 0.94 : 1;
  const left = `${baseX + offset.x + (debugLayout ? debugOffset.x : 0)}px`;
  const top = `${baseY + offset.y - bottomNudge - 150 + (debugLayout ? debugOffset.y : 0)}px`;
  const isFolded = player.status === 'folded';
  const isActive = player.status === 'active' || player.status === 'allin';
  const showCards = player.status !== 'out' && player.status !== 'sitout' && player.status !== 'busted' && player.status !== 'folded';
  const cardList = showCards
    ? ((player.hole_cards && player.hole_cards.length > 0)
      ? player.hole_cards
      : (player.cards && player.cards.length > 0 ? player.cards : ['??', '??']))
    : [];
  const avatar = avatarOverride ?? SEAT_AVATARS[index % SEAT_AVATARS.length];
  const nickname = player.nickname || `Player ${index + 1}`;
  const nameLabel = nickname.length > 10 ? `${nickname.slice(0, 10)}…` : nickname;
  const totalPaid = Number.isFinite(paidTotal) ? Number(paidTotal) : 0;
  const showPaid = totalPaid > 0;
  const statusLabel = player.status === 'allin'
    ? 'ALL-IN'
    : player.status === 'folded'
      ? 'FOLD'
      : player.status === 'busted'
        ? 'BUSTED'
        : player.status === 'sitout'
          ? 'SITOUT'
          : player.status === 'out'
            ? 'OUT'
            : undefined;
  
  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (debugLayout) {
      event.preventDefault();
      dragRef.current = {
        startX: event.clientX,
        startY: event.clientY,
        offsetX: debugOffsetRef.current.x,
        offsetY: debugOffsetRef.current.y
      };
    }
    onPointerDown?.(event);
  };

  React.useLayoutEffect(() => {
    if (!onAvatarAnchor || !avatarRef.current) return;
    const node = avatarRef.current;
    const update = () => {
      const rect = node.getBoundingClientRect();
      onAvatarAnchor(player.sid, rect);
    };
    update();
    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(update);
      observer.observe(node);
      window.addEventListener('resize', update);
      return () => {
        observer.disconnect();
        window.removeEventListener('resize', update);
      };
    }
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('resize', update);
    };
  }, [onAvatarAnchor, player.sid, left, top, seatScale, debugOffset.x, debugOffset.y, layoutNonce]);

  return (
    <div 
      className="absolute w-44 flex flex-col items-center gap-2"
      style={{ left, top, transform: `translate(-50%, -50%) scale(${seatScale})`, cursor: debugLayout || onPointerDown ? 'grab' : 'default' }}
      onPointerDown={handlePointerDown}
      onDoubleClick={() => {
        if (!debugLayout || typeof window === 'undefined') return;
        debugOffsetRef.current = { x: 0, y: 0 };
        setDebugOffset({ x: 0, y: 0 });
        try {
          const raw = window.localStorage.getItem(storageKey);
          const parsed = raw ? JSON.parse(raw) : {};
          delete parsed[index];
          window.localStorage.setItem(storageKey, JSON.stringify(parsed));
          console.log('[Texas SeatLayout] reset', { index, totalPlayers });
        } catch {
        }
      }}
    >
      {debugLayout && (
        <div className="absolute -top-6 left-1/2 -translate-x-1/2 text-[10px] px-2 py-0.5 rounded-full bg-black/70 text-emerald-200 border border-emerald-400/40">
          {Math.round(debugOffset.x)},{Math.round(debugOffset.y)}
        </div>
      )}
      {/* Cards */}
      <div className="flex gap-1 z-0 items-center justify-center">
        {cardList.map((card, i) => {
          const parsed = parseCard(card);
          if (!parsed && card && card !== '??' && process.env.NODE_ENV === 'development') {
            console.warn('[Texas] card parse failed', { card, player: player.nickname, sid: player.sid });
          }
          return (
            <motion.div 
              key={i}
              initial={{ y: 10, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: i * 0.08 }}
              className={isFolded ? 'opacity-50 grayscale' : ''}
            >
              {parsed ? (
                 <PlayingCard rank={parsed.rank} suit={parsed.suit} compact showRank className="w-10 h-14 text-xs shadow-lg" />
              ) : (
                 <PlayingCard rank="A" suit="spades" hidden compact className="w-10 h-14 text-xs shadow-lg" />
              )}
            </motion.div>
          );
        })}
      </div>

      {/* Avatar + Blinds/Dealer */}
      <div className="relative flex items-center justify-center">
        {isCurrentTurn && (
          <div className={`absolute -inset-4 rounded-full blur-xl animate-pulse ${
            isAgent ? 'bg-emerald-400/22' : 'bg-emerald-300/32'
          }`} />
        )}
        {(isSmallBlind || isBigBlind) && (
          <div className={`absolute -inset-2 rounded-full blur-lg animate-pulse ${
            isSmallBlind
              ? (isAgent ? 'bg-cyan-400/25' : 'bg-amber-300/25')
              : (isAgent ? 'bg-fuchsia-400/25' : 'bg-orange-300/25')
          }`} />
        )}
        <AgentSummaryHover agentId={player.sid} agentName={player.nickname} isAgent={isAgent}>
          <div
            ref={avatarRef}
            className={`relative w-16 h-16 rounded-full border-2 ${
            isSmallBlind
              ? (isAgent ? 'border-cyan-300 shadow-[0_0_24px_rgba(34,211,238,0.55)]' : 'border-amber-400 shadow-[0_0_18px_rgba(251,191,36,0.25)]')
              : isBigBlind
                ? (isAgent ? 'border-fuchsia-300 shadow-[0_0_24px_rgba(217,70,239,0.55)]' : 'border-orange-400 shadow-[0_0_18px_rgba(249,115,22,0.25)]')
                : (isActive ? 'border-emerald-400 shadow-[0_0_18px_rgba(52,211,153,0.35)]' : 'border-slate-500/60')
          } ${isAgent ? 'bg-[#0b0b14]/90' : 'bg-slate-900/90'} ${isWinner ? (isAgent ? 'ring-4 ring-amber-300/80 shadow-[0_0_30px_rgba(251,191,36,0.65)]' : 'ring-4 ring-amber-400/70 shadow-[0_0_22px_rgba(251,191,36,0.4)]') : ''} flex items-center justify-center overflow-hidden z-10 transition-all duration-300 ${isSmallBlind || isBigBlind || isCurrentTurn ? 'scale-110' : ''}`}
          >
            <span className="text-2xl">{avatar}</span>
          </div>
        </AgentSummaryHover>
        {(isDealer || isSmallBlind || isBigBlind) && (
          <div className="absolute top -right-6 flex flex-col gap-1 items-end z-30">
            {isDealer && (
              <div className={`px-2.5 py-0.5 rounded-full text-sm font-bold ${isAgent ? 'bg-sky-500/20 text-sky-100 border border-sky-400/60 shadow-[0_0_14px_rgba(56,189,248,0.6)]' : 'bg-emerald-100 text-emerald-700 border border-emerald-200'}`}>
                D
              </div>
            )}
            {isSmallBlind && (
              <div className={`px-2.5 py-0.5 rounded-full text-sm font-bold ${isAgent ? 'bg-cyan-500/20 text-cyan-100 border border-cyan-400/60 shadow-[0_0_14px_rgba(34,211,238,0.6)]' : 'bg-amber-100 text-amber-700 border border-amber-200'}`}>
                SB
              </div>
            )}
            {isBigBlind && (
              <div className={`px-2.5 py-0.5 rounded-full text-sm font-bold ${isAgent ? 'bg-fuchsia-500/20 text-fuchsia-100 border border-fuchsia-400/60 shadow-[0_0_14px_rgba(217,70,239,0.6)]' : 'bg-orange-100 text-orange-700 border border-orange-200'}`}>
                BB
              </div>
            )}
          </div>
        )}
      </div>

      <div className={`text-[10px] uppercase tracking-[0.24em] ${
        isAgent ? 'text-emerald-200/80' : 'text-emerald-700/80'
      }`}>
        {nameLabel}
      </div>

      {(isCurrentTurn || isSpeaking || statusLabel) && (
        <div className={`-mt-1 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-widest shadow-lg border ${
          statusLabel
            ? (player.status === 'busted'
              ? (isAgent ? 'bg-rose-500/20 text-rose-100 border-rose-400/40' : 'bg-rose-100 text-rose-700 border-rose-200')
              : player.status === 'sitout'
                ? (isAgent ? 'bg-slate-500/20 text-slate-100 border-slate-400/40' : 'bg-slate-100 text-slate-700 border-slate-200')
                : (isAgent ? 'bg-amber-500/20 text-amber-100 border-amber-400/40' : 'bg-amber-100 text-amber-700 border-amber-200'))
            : isSpeaking
              ? (isAgent ? 'bg-emerald-400/25 text-emerald-100 border-emerald-300/40' : 'bg-emerald-100 text-emerald-700 border-emerald-200')
              : (isAgent ? 'bg-emerald-500/20 text-emerald-100 border-emerald-400/40' : 'bg-emerald-100 text-emerald-700 border-emerald-200')
        }`}>
          {statusLabel || (isSpeaking ? 'ACTION' : 'TURN')}
        </div>
      )}

      {/* Info Box */}
      <div className={`w-full rounded-3xl border px-6 py-2.5 text-center backdrop-blur-md ${
        isAgent ? 'bg-black/70 border-emerald-500/20' : 'bg-white/90 border-slate-200 shadow-sm'
      }`}>
        <div className="mt-1 flex items-center justify-center gap-3 text-[12px] font-mono">
          <div className={`flex items-center gap-1 ${isAgent ? 'text-emerald-300' : 'text-emerald-600'}`}>
            <span>LEFT</span>
            <span>🪙{formatChips(player.chips)}</span>
          </div>
          <div className={`flex items-center gap-1 ${isAgent ? 'text-amber-200' : 'text-amber-700'}`}>
            <span>IN</span>
            <span>🪙{formatChips(totalPaid)}</span>
          </div>
        </div>
      </div>
      {player.status === 'busted' && (
        <div className={`text-[10px] uppercase tracking-[0.3em] ${
          isAgent ? 'text-rose-200/80' : 'text-rose-600/80'
        }`}>
          Spectate / Exit
        </div>
      )}

    </div>
  );
}

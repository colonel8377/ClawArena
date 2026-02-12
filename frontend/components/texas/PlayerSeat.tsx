'use client';

import React from 'react';
import { SpectatorPlayer } from '@/store/types';
import PlayingCard from '../poker/PlayingCard'; 
import { parseCard } from '../poker/utils';
import { getSeatPosition } from './seatPositions';
import EquityGauge from './EquityGauge';
import { motion } from 'framer-motion';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';

interface PlayerSeatProps {
  player: SpectatorPlayer;
  index: number;
  totalPlayers: number;
  center: AnchoredCenter;
  isAgent?: boolean;
  isDealer?: boolean;
  isSmallBlind?: boolean;
  isBigBlind?: boolean;
  pot?: number;
  winners?: string[];
}

const AVATARS = ['😺', '🐶', '🐵', '🦊', '🐸', '🐼', '🐻', '🐯', '🦁', '🐷', '🐨', '🐧', '🦄', '🐙', '🦉', '🐺'];

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
  isAgent = true,
  isDealer = false,
  isSmallBlind = false,
  isBigBlind = false,
  pot,
  winners
}: PlayerSeatProps) {
  const offset = getSeatPosition(index, totalPlayers, center.stageSize);
  const baseX = Number.isFinite(center.pixel.x) ? center.pixel.x : center.stageSize.width / 2;
  const baseY = Number.isFinite(center.pixel.y) ? center.pixel.y : center.stageSize.height / 2;
  const bottomNudge = offset.y > 0 ? Math.min(38, offset.y * 0.15) : 0;
  const left = `${baseX + offset.x}px`;
  const top = `${baseY + offset.y - bottomNudge}px`;
  const isFolded = player.status === 'folded';
  const isActive = player.status === 'active' || player.status === 'allin';
  const isWinner = Boolean(winners?.includes(player.sid) || winners?.includes(player.nickname));
  const winnerAmount = isWinner && pot && winners?.length ? Math.floor(pot / winners.length) : undefined;
  const avatar = AVATARS[hashString(player.sid || player.nickname) % AVATARS.length];
  const initials = player.nickname?.slice(0, 2).toUpperCase();
  const hasBet = Boolean(player.current_bet && player.current_bet > 0);
  
  return (
    <div 
      className="absolute w-44 flex flex-col items-center gap-2"
      style={{ left, top, transform: 'translate(-50%, -50%)' }}
    >
      {/* Cards */}
      <div className="flex gap-1 z-0 items-center justify-center">
        {(player.hole_cards || player.cards || ['??', '??']).map((card, i) => {
          const parsed = parseCard(card);
          return (
            <motion.div 
              key={i}
              initial={{ y: 10, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: i * 0.08 }}
              className={isFolded ? 'opacity-50 grayscale' : ''}
            >
              {parsed ? (
                 <PlayingCard rank={parsed.rank} suit={parsed.suit} className="w-10 h-14 text-xs shadow-lg" />
              ) : (
                 <PlayingCard rank="A" suit="spades" hidden className="w-10 h-14 text-xs shadow-lg" />
              )}
            </motion.div>
          );
        })}
      </div>

      {/* Avatar + Blinds/Dealer */}
      <div className="relative flex items-center justify-center">
        {(isSmallBlind || isBigBlind) && (
          <div className={`absolute -inset-2 rounded-full blur-lg animate-pulse ${
            isSmallBlind
              ? (isAgent ? 'bg-amber-400/18' : 'bg-amber-300/25')
              : (isAgent ? 'bg-orange-400/18' : 'bg-orange-300/25')
          }`} />
        )}
        <div className={`relative w-16 h-16 rounded-full border-2 ${
          isSmallBlind
            ? (isAgent ? 'border-amber-300 shadow-[0_0_22px_rgba(251,191,36,0.45)]' : 'border-amber-400 shadow-[0_0_18px_rgba(251,191,36,0.25)]')
            : isBigBlind
              ? (isAgent ? 'border-orange-300 shadow-[0_0_22px_rgba(249,115,22,0.45)]' : 'border-orange-400 shadow-[0_0_18px_rgba(249,115,22,0.25)]')
              : (isActive ? 'border-emerald-400 shadow-[0_0_18px_rgba(52,211,153,0.35)]' : 'border-slate-500/60')
        } bg-slate-900/90 flex items-center justify-center overflow-hidden z-10 transition-all duration-300 ${isSmallBlind || isBigBlind ? 'scale-110' : ''}`}>
          <span className="text-xs font-bold text-emerald-100">{initials}</span>
          <span className="absolute -bottom-2 -right-2 text-lg">{avatar}</span>
        </div>
        {(isDealer || isSmallBlind || isBigBlind) && (
          <div className="absolute -top-2 -right-3 flex flex-col gap-1 items-end">
            {isDealer && (
              <div className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${isAgent ? 'bg-emerald-500/20 text-emerald-200 border border-emerald-500/40' : 'bg-emerald-100 text-emerald-700 border border-emerald-200'}`}>
                D
              </div>
            )}
            {isSmallBlind && (
              <div className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${isAgent ? 'bg-amber-500/25 text-amber-100 border border-amber-400/50' : 'bg-amber-100 text-amber-700 border border-amber-200'}`}>
                SB
              </div>
            )}
            {isBigBlind && (
              <div className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${isAgent ? 'bg-orange-500/30 text-orange-100 border border-orange-400/50' : 'bg-orange-100 text-orange-700 border border-orange-200'}`}>
                BB
              </div>
            )}
          </div>
        )}
      </div>

      {/* Info Box */}
      <div className={`w-full rounded-2xl border px-3.5 py-2.5 text-center backdrop-blur-md ${
        isAgent ? 'bg-black/70 border-emerald-500/20' : 'bg-white/90 border-slate-200 shadow-sm'
      }`}>
        <div className={`text-sm font-semibold tracking-wide truncate ${isAgent ? 'text-emerald-100' : 'text-slate-700'}`} title={player.nickname}>
          {player.nickname}
        </div>
        <div className="mt-1 flex items-center justify-center gap-3 text-xs font-mono">
          <div className={`flex items-center gap-1 ${isAgent ? 'text-emerald-300' : 'text-emerald-600'}`}>
            <span>💰</span>
            <span>{formatChips(player.chips)}</span>
          </div>
          <div className={`flex items-center gap-1 ${hasBet ? (isAgent ? 'text-amber-300' : 'text-amber-600') : (isAgent ? 'text-slate-400' : 'text-slate-400')}`}>
            <span>🪙</span>
            <span>{formatChips(player.current_bet || 0)}</span>
          </div>
        </div>
        {isWinner && (
          <div className={`mt-1 text-xl font-black tracking-wide ${isAgent ? 'text-emerald-200' : 'text-emerald-700'}`}>
            WIN +{formatChips(winnerAmount || 0)}
          </div>
        )}
      </div>

      {/* Current Bet Bubble */}
      {hasBet ? (
        <div className={`absolute -top-3 right-0 text-[10px] font-bold px-2 py-0.5 rounded-full shadow-lg z-30 ${
          isAgent ? 'bg-amber-500/20 text-amber-200 border border-amber-400/40' : 'bg-amber-100 text-amber-700 border border-amber-200'
        }`}>
          ${formatChips(player.current_bet)}
        </div>
      ) : null}

      {/* Equity/Action Gauge */}
      {!isFolded && (
        <EquityGauge cards={player.hole_cards || player.cards || []} />
      )}
    </div>
  );
}

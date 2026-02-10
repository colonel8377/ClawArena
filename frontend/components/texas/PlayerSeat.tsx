'use client';

import React from 'react';
import { SpectatorPlayer } from '@/store/types';
import PlayingCard from '../poker/PlayingCard'; 
import { parseCard } from '../poker/utils';
import { getSeatPosition } from './seatPositions';
import EquityGauge from './EquityGauge';
import { motion } from 'framer-motion';

interface PlayerSeatProps {
  player: SpectatorPlayer;
  index: number;
  totalPlayers: number;
  communityCards: string[];
}

export default function PlayerSeat({ player, index, totalPlayers, communityCards }: PlayerSeatProps) {
  const pos = getSeatPosition(index, totalPlayers);
  const isFolded = player.status === 'folded';
  const isActive = player.status === 'active' || player.status === 'allin';
  
  return (
    <div 
      className="absolute w-32 h-32 flex flex-col items-center justify-center"
      style={{ left: pos.x, top: pos.y, transform: 'translate(-50%, -50%)' }}
    >
      {/* Avatar Circle */}
      <div className={`relative w-16 h-16 rounded-full border-2 ${isActive ? 'border-green-500 shadow-[0_0_15px_rgba(34,197,94,0.5)]' : 'border-gray-600 grayscale'} bg-gray-900 flex items-center justify-center overflow-hidden z-10 transition-all duration-300`}>
        <span className="text-xl font-bold text-gray-300">{player.nickname.substring(0, 2).toUpperCase()}</span>
      </div>

      {/* Info Box */}
      <div className="mt-2 bg-gray-900/90 border border-gray-700 rounded px-2 py-1 text-center w-full z-20">
        <div className="text-xs text-white font-mono truncate">{player.nickname}</div>
        <div className="text-xs text-yellow-400 font-mono flex items-center justify-center gap-1">
          <span>$</span>
          <span>{player.chips}</span>
        </div>
      </div>

      {/* Cards */}
      <div className="absolute -top-8 flex gap-1 z-0">
        {(player.hole_cards || player.cards || ['??', '??']).map((card, i) => {
          const parsed = parseCard(card);
          return (
            <motion.div 
              key={i}
              initial={{ y: 10, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: i * 0.1 }}
              className={isFolded ? 'opacity-50 grayscale' : ''}
            >
              {parsed ? (
                 <PlayingCard rank={parsed.rank} suit={parsed.suit} className="w-10 h-14 text-xs" />
              ) : (
                 <PlayingCard rank="A" suit="spades" hidden className="w-10 h-14 text-xs" />
              )}
            </motion.div>
          );
        })}
      </div>

      {/* Current Bet Bubble */}
      {player.current_bet && player.current_bet > 0 ? (
        <div className="absolute -top-4 right-0 bg-yellow-500 text-black text-[10px] font-bold px-1.5 py-0.5 rounded-full shadow-lg z-30">
          ${player.current_bet}
        </div>
      ) : null}

      {/* Equity/Action Gauge */}
      {!isFolded && (
        <EquityGauge cards={player.hole_cards || player.cards || []} communityCards={communityCards} />
      )}
    </div>
  );
}

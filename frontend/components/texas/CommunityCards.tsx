'use client';

import React from 'react';

import PlayingCard from '../poker/PlayingCard';
import { parseCard } from '../poker/utils';
import { motion } from 'framer-motion';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';

interface CommunityCardsProps {
  cards: string[];
  center?: AnchoredCenter;
}

export default function CommunityCards({ cards, center }: CommunityCardsProps) {
  const leftPercent = center?.percent.left ?? '50%';

  return (
    <motion.div 
      layout
      className="absolute -translate-x-1/2 flex flex-col items-center gap-3 z-20"
      style={{ left: leftPercent, top: '34%' }}
    >
      <div className="relative px-6 py-4 rounded-3xl border border-white/30 bg-black/70 shadow-[0_12px_35px_rgba(0,0,0,0.55)] backdrop-blur-xl">
        <div className="absolute inset-0 flex items-center justify-center text-8xl opacity-10 select-none pointer-events-none">
          🃏
        </div>
        <div className="relative flex gap-3">
          {cards.map((card, i) => {
            const parsed = parseCard(card);
            if (!parsed) return null;
            
            return (
              <motion.div
                key={`${card}-${i}`}
                layout
                initial={{ scale: 0.9, opacity: 0, rotateY: 90 }}
                animate={{ scale: 1, opacity: 1, rotateY: 0 }}
                transition={{ type: 'spring', bounce: 0.4, duration: 0.5 + i * 0.05 }}
              >
                <PlayingCard rank={parsed.rank} suit={parsed.suit} className="w-20 h-28 text-base shadow-2xl" />
              </motion.div>
            );
          })}
          {[...Array(Math.max(0, 5 - cards.length))].map((_, i) => (
            <div
              key={`empty-${i}`}
              className="w-20 h-28 rounded-xl border-2 border-dashed border-white/30 bg-black/20 flex items-center justify-center text-3xl opacity-40"
            >
              🃏
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}

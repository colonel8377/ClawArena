'use client';

import React from 'react';
import PlayingCard from '../poker/PlayingCard';
import { parseCard } from '../poker/utils';
import { motion } from 'framer-motion';

interface CommunityCardsProps {
  cards: string[];
}

export default function CommunityCards({ cards }: CommunityCardsProps) {
  return (
    <div className="absolute top-[40%] left-1/2 -translate-x-1/2 flex gap-2">
      {cards.map((card, i) => {
        const parsed = parseCard(card);
        if (!parsed) return null;
        
        return (
          <motion.div
            key={`${card}-${i}`}
            initial={{ scale: 0.8, opacity: 0, y: -20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            transition={{ type: 'spring', bounce: 0.5 }}
          >
            <PlayingCard rank={parsed.rank} suit={parsed.suit} className="w-14 h-20 text-sm shadow-xl" />
          </motion.div>
        );
      })}

      
      {/* Empty Slots Placeholders */}
      {[...Array(5 - cards.length)].map((_, i) => (
        <div key={`empty-${i}`} className="w-14 h-20 border-2 border-dashed border-gray-700 rounded bg-black/20" />
      ))}
    </div>
  );
}

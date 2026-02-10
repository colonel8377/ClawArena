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
    <motion.div 
      layout
      className="absolute top-[40%] left-1/2 -translate-x-1/2 flex gap-2"
    >
      {cards.map((card, i) => {
        const parsed = parseCard(card);
        if (!parsed) return null;
        
        return (
          <motion.div
            key={`${card}-${i}`}
            layout
            initial={{ scale: 0, opacity: 0, rotateY: 90 }}
            animate={{ scale: 1, opacity: 1, rotateY: 0 }}
            transition={{ type: 'spring', bounce: 0.5, duration: 0.6 }}
          >
            <PlayingCard rank={parsed.rank} suit={parsed.suit} className="w-14 h-20 text-sm shadow-xl" />
          </motion.div>
        );
      })}

      
      {/* Empty Slots Placeholders */}
      {[...Array(5 - cards.length)].map((_, i) => (
        <div key={`empty-${i}`} className="w-14 h-20 border-2 border-dashed border-gray-700 rounded bg-black/20" />
      ))}
    </motion.div>
  );
}

'use client';

import React, { useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { SpectatorPlayer } from '@/store/types';
import { getSeatPosition } from '@/components/texas/seatPositions';

interface ChipStreamProps {
  players: SpectatorPlayer[];
  pot: number;
  dealerPosition?: number;
}

interface FlyingChip {
  id: string;
  from: { x: string; y: string };
  to: { x: string; y: string };
  amount: number;
  color: string;
}

const POT_POSITION = { x: '50%', y: '40%' };

export default function ChipStream({ players }: ChipStreamProps) {
  const [chips, setChips] = useState<FlyingChip[]>([]);
  const prevBets = useRef<Record<string, number>>({});

  useEffect(() => {
    players.forEach((p, index) => {
      const oldBet = prevBets.current[p.sid] || 0;
      const newBet = p.current_bet || 0;

      if (newBet > oldBet) {
        const diff = newBet - oldBet;
        const startPos = getSeatPosition(index, players.length);
        
        const newChip: FlyingChip = {
          id: `${p.sid}-${Date.now()}-${Math.random()}`,
          from: startPos,
          to: POT_POSITION,
          amount: diff,
          color: 'bg-yellow-400', // Default chip color
        };

        setChips((prev) => [...prev, newChip]);
      }
      prevBets.current[p.sid] = newBet;
    });
  }, [players]);

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden z-20">
      <AnimatePresence>
        {chips.map((chip) => (
          <motion.div
            key={chip.id}
            initial={{ left: chip.from.x, top: chip.from.y, opacity: 0, scale: 0.5, rotate: 0 }}
            animate={{ left: chip.to.x, top: chip.to.y, opacity: 1, scale: 1, rotate: 360 }}
            exit={{ opacity: 0, scale: 0.2 }}
            transition={{ duration: 0.8, ease: "easeInOut" }}
            onAnimationComplete={() => {
              setChips((prev) => prev.filter((c) => c.id !== chip.id));
            }}
            className={`absolute w-6 h-6 rounded-full border-2 border-dashed border-white shadow-lg ${chip.color} flex items-center justify-center text-[8px] text-black font-bold`}
          >
            $
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

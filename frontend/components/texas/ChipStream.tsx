'use client';

import React, { useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { SpectatorPlayer } from '@/store/types';
import { getSeatPosition } from '@/components/texas/seatPositions';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';

interface ChipStreamProps {
  players: SpectatorPlayer[];
  pot: number;
  dealerPosition?: number;
  center?: AnchoredCenter;
}

interface FlyingChip {
  id: string;
  from: { left: string; top: string };
  to: { left: string; top: string };
  amount: number;
  color: string;
}

const defaultCenter: AnchoredCenter = {
  percent: { left: '50%', top: '50%' },
  pixel: { x: 0, y: 0 },
  stageSize: { width: 0, height: 0 }
};

export default function ChipStream({ players, center = defaultCenter }: ChipStreamProps) {
  const [chips, setChips] = useState<FlyingChip[]>([]);
  const prevBets = useRef<Record<string, number>>({});
  const seatOrigin = center.pixel.x !== 0 || center.pixel.y !== 0
    ? center.pixel
    : {
        x: center.stageSize.width / 2,
        y: center.stageSize.height / 2
      };
  const potPosition = React.useMemo(() => {
    const stageHeight = center.stageSize.height || 0;
    const top = stageHeight ? Math.max(stageHeight * 0.35, 80) : 0;
    return {
      left: `${seatOrigin.x}px`,
      top: `${top}px`
    };
  }, [center.stageSize.height, seatOrigin.x]);

  useEffect(() => {
    players.forEach((p, index) => {
      const oldBet = prevBets.current[p.sid] || 0;
      const newBet = p.current_bet || 0;

      if (newBet > oldBet) {
        const diff = newBet - oldBet;
        const offset = getSeatPosition(index, players.length, center.stageSize);
        const startPos = {
          left: `${seatOrigin.x + offset.x}px`,
          top: `${seatOrigin.y + offset.y}px`
        };
        
        const newChip: FlyingChip = {
          id: `${p.sid}-${Date.now()}-${Math.random()}`,
          from: startPos,
          to: potPosition,
          amount: diff,
          color: 'bg-yellow-400', // Default chip color
        };

        setChips((prev) => [...prev, newChip]);
      }
      prevBets.current[p.sid] = newBet;
    });
  }, [players, center, potPosition, seatOrigin.x, seatOrigin.y]);

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden z-20">
      <AnimatePresence>
        {chips.map((chip) => (
          <motion.div
            key={chip.id}
            initial={{ left: chip.from.left, top: chip.from.top, opacity: 0, scale: 0.5, rotate: 0 }}
            animate={{ left: chip.to.left, top: chip.to.top, opacity: 1, scale: 1, rotate: 360 }}
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

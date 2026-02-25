'use client';

import React, { useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { SpectatorPlayer } from '@/store/types';
import { getSeatPosition } from '@/components/texas/seatPositions';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';

interface ChipStreamProps {
  players: SpectatorPlayer[];
  center?: AnchoredCenter;
  seatAnchors?: Record<string, { x: number; y: number }>;
  potAnchor?: { x: number; y: number } | null;
  settlement?: { id: string; payouts: Record<string, number> } | null;
}

interface FlyingChip {
  id: string;
  from: { x: number; y: number };
  to: { x: number; y: number };
  amount: number;
  color: string;
  kind: 'bet' | 'payout';
}

const defaultCenter: AnchoredCenter = {
  percent: { left: '50%', top: '50%' },
  pixel: { x: 0, y: 0 },
  stageSize: { width: 0, height: 0 }
};

export default function ChipStream({ players, center = defaultCenter, seatAnchors, potAnchor, settlement }: ChipStreamProps) {
  const [chips, setChips] = useState<FlyingChip[]>([]);
  const prevBets = useRef<Record<string, number>>({});
  const lastSettlementId = useRef<string | null>(null);
  const seatOrigin = center.pixel.x !== 0 || center.pixel.y !== 0
    ? center.pixel
    : {
        x: center.stageSize.width / 2,
        y: center.stageSize.height / 2
      };
  const potPosition = React.useMemo(() => {
    if (potAnchor) {
      return { x: potAnchor.x, y: potAnchor.y };
    }
    const stageHeight = center.stageSize.height || 0;
    const top = stageHeight ? Math.max(stageHeight * 0.35, 80) : 0;
    return {
      x: seatOrigin.x,
      y: top
    };
  }, [center.stageSize.height, potAnchor, seatOrigin.x]);

  useEffect(() => {
    players.forEach((p, index) => {
      const oldBet = prevBets.current[p.sid] || 0;
      const newBet = p.current_bet || 0;

      if (newBet > oldBet) {
        const diff = newBet - oldBet;
        const anchor = seatAnchors?.[p.sid];
        const offset = anchor ?? (() => {
          const seat = getSeatPosition(index, players.length, center.stageSize);
          return { x: seatOrigin.x + seat.x, y: seatOrigin.y + seat.y };
        })();
        
        const newChip: FlyingChip = {
          id: `${p.sid}-${Date.now()}-${Math.random()}`,
          from: { x: offset.x, y: offset.y },
          to: potPosition,
          amount: diff,
          color: 'bg-yellow-400', // Default chip color
          kind: 'bet',
        };

        setChips((prev) => [...prev, newChip]);
      }
      prevBets.current[p.sid] = newBet;
    });
  }, [players, center, potPosition, seatOrigin.x, seatOrigin.y, seatAnchors]);

  useEffect(() => {
    if (!settlement?.id || settlement.id === lastSettlementId.current) return;
    lastSettlementId.current = settlement.id;
    const payouts = settlement.payouts || {};
    const payoutEntries = Object.entries(payouts)
      .filter(([, amount]) => Number(amount) > 0);
    if (payoutEntries.length === 0) return;

    const newChips: FlyingChip[] = [];
    payoutEntries.forEach(([sid, rawAmount], index) => {
      const amount = Number(rawAmount) || 0;
      const anchor = seatAnchors?.[sid];
      const fallbackSeat = getSeatPosition(index, players.length, center.stageSize);
      const target = anchor ?? { x: seatOrigin.x + fallbackSeat.x, y: seatOrigin.y + fallbackSeat.y };
      const chipCount = Math.min(4, Math.max(1, Math.round(Math.log10(Math.max(1, amount)))));
      for (let i = 0; i < chipCount; i += 1) {
        newChips.push({
          id: `payout-${sid}-${settlement.id}-${i}`,
          from: potPosition,
          to: target,
          amount,
          color: 'bg-emerald-300',
          kind: 'payout',
        });
      }
    });
    if (newChips.length > 0) {
      setChips((prev) => [...prev, ...newChips]);
    }
  }, [settlement, seatAnchors, potPosition, players.length, center.stageSize, seatOrigin.x, seatOrigin.y]);

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden z-20">
      <AnimatePresence>
        {chips.map((chip) => (
          <motion.div
            key={chip.id}
            initial={{ x: chip.from.x, y: chip.from.y, opacity: 0, scale: 0.5, rotate: 0 }}
            animate={{ x: chip.to.x, y: chip.to.y, opacity: 1, scale: 1, rotate: chip.kind === 'payout' ? -360 : 360 }}
            exit={{ opacity: 0, scale: 0.2 }}
            transition={{ duration: chip.kind === 'payout' ? 0.9 : 0.8, ease: 'easeInOut' }}
            onAnimationComplete={() => {
              setChips((prev) => prev.filter((c) => c.id !== chip.id));
            }}
            className={`absolute left-0 top-0 w-6 h-6 rounded-full border-2 border-dashed border-white shadow-lg ${chip.color} flex items-center justify-center text-[8px] text-black font-bold`}
          >
            $
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

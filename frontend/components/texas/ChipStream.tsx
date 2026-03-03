'use client';

import React, { useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { SpectatorPlayer } from '@/store/types';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';

interface ChipStreamProps {
  players: SpectatorPlayer[];
  center?: AnchoredCenter;
  seatAnchors?: Record<string, { x: number; y: number }>;
  potAnchor?: { x: number; y: number } | null;
  paidMap?: Record<string, number>;
  settlement?: { id: string; payouts: Record<string, number> } | null;
  handNumber?: number | null;
}

interface FlyingChip {
  id: string;
  from: { x: number; y: number };
  to: { x: number; y: number };
  amount: number;
  color: string;
  kind: 'bet' | 'payout';
}



export default function ChipStream({ players, seatAnchors, potAnchor, paidMap, settlement, handNumber }: ChipStreamProps) {
  const [chips, setChips] = useState<FlyingChip[]>([]);
  const prevBets = useRef<Record<string, number>>({});
  const pendingBets = useRef<Record<string, number>>({});
  const lastSettlementId = useRef<string | null>(null);
  const potPosition = React.useMemo(() => {
    if (potAnchor) {
      return { x: potAnchor.x, y: potAnchor.y };
    }
    return null;
  }, [potAnchor]);

  useEffect(() => {
    prevBets.current = {};
    pendingBets.current = {};
    setChips([]);
  }, [handNumber]);

  useEffect(() => {
    players.forEach((p) => {
      const oldBet = prevBets.current[p.sid] || 0;
      const paidValue = paidMap && Number.isFinite(paidMap[p.sid]) ? Number(paidMap[p.sid]) : undefined;
      const newBet = paidValue !== undefined ? paidValue : (p.current_bet || 0);

      if (newBet > oldBet) {
        const diff = newBet - oldBet;
        pendingBets.current[p.sid] = (pendingBets.current[p.sid] || 0) + diff;
      }
      prevBets.current[p.sid] = newBet;
    });

    if (!potPosition) return;
    Object.entries(pendingBets.current).forEach(([sid, amount]) => {
      const anchor = seatAnchors?.[sid];
      if (!anchor) return;
      const newChip: FlyingChip = {
        id: `${sid}-${Date.now()}-${Math.random()}`,
        from: { x: anchor.x, y: anchor.y },
        to: potPosition,
        amount,
        color: 'bg-yellow-400',
        kind: 'bet',
      };
      setChips((prev) => [...prev, newChip]);
      delete pendingBets.current[sid];
    });
  }, [players, potPosition, seatAnchors, paidMap]);

  useEffect(() => {
    if (!settlement?.id || settlement.id === lastSettlementId.current) return;
    lastSettlementId.current = settlement.id;
    const payouts = settlement.payouts || {};
    if (!potPosition) return;
    const payoutEntries = Object.entries(payouts)
      .filter(([, amount]) => Number(amount) > 0);
    if (payoutEntries.length === 0) return;

    const newChips: FlyingChip[] = [];
    payoutEntries.forEach(([sid, rawAmount]) => {
      const amount = Number(rawAmount) || 0;
      const anchor = seatAnchors?.[sid];
      if (!anchor) return;
      
      const target = anchor;
      
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
  }, [settlement, seatAnchors, potPosition]);

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

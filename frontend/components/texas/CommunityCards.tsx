'use client';

import React from 'react';

import PlayingCard from '../poker/PlayingCard';
import { parseCard } from '../poker/utils';
import { motion } from 'framer-motion';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';

interface CommunityCardsProps {
  cards: string[];
  center?: AnchoredCenter;
  offset?: { x: number; y: number };
  onPointerDown?: (event: React.PointerEvent<HTMLDivElement>) => void;
}

export default function CommunityCards({ cards, offset, onPointerDown }: CommunityCardsProps) {
  const left = '50%';
  const top = '12%';
  const visibleCards = cards.filter((card) => Boolean(parseCard(card)));
  React.useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return;
    const parsed = cards.map((card) => ({ card, parsed: parseCard(card) }));
    console.log('[Texas] community cards render', parsed);
  }, [cards]);
  if (visibleCards.length === 0) return null;
  const offsetX = offset?.x ?? 0;
  const offsetY = offset?.y ?? 0;
  const interactive = Boolean(onPointerDown);

  return (
    <div
      className="absolute flex flex-col items-center gap-3 z-20"
      style={{
        left,
        top,
        transform: `translate(-50%, 0) translate(${offsetX}px, ${offsetY}px)`,
        cursor: interactive ? 'grab' : undefined,
        pointerEvents: interactive ? 'auto' : undefined,
        userSelect: interactive ? 'none' : undefined,
        touchAction: interactive ? 'none' : undefined
      }}
      onPointerDown={onPointerDown}
    >
      <div className="relative px-6 py-3 rounded-3xl border border-white/15 bg-black/25 shadow-[inset_0_0_18px_rgba(0,0,0,0.35)] backdrop-blur-sm">
        <div className="relative flex gap-3">
          {visibleCards.map((card, i) => {
            const parsed = parseCard(card);
            if (parsed) {
              return (
                <motion.div
                  key={`${card}-${i}`}
                  initial={{ scale: 0.9, opacity: 0, rotateY: 90 }}
                  animate={{ scale: 1, opacity: 1, rotateY: 0 }}
                  transition={{ type: 'spring', bounce: 0.4, duration: 0.5 + i * 0.05 }}
                >
                  <PlayingCard rank={parsed.rank} suit={parsed.suit} className="w-20 h-28 text-base shadow-2xl" />
                </motion.div>
              );
            }
            return null;
          })}
        </div>
      </div>
    </div>
  );
}

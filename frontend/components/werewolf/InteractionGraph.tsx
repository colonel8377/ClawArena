'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { getWerewolfSeatPosition } from './layoutUtils';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';

interface InteractionGraphProps {
  players: { sid: string }[];
  center?: AnchoredCenter;
  isAgent?: boolean;
  seatRadius?: number;
  lineRadius?: number;
  voteCounts?: Record<string, number>;
}

export default function InteractionGraph({ players, center, isAgent = true, seatRadius, voteCounts }: InteractionGraphProps) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [size, setSize] = React.useState({ width: 0, height: 0 });

  React.useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setSize({ width: rect.width, height: rect.height });
    };

    updateSize();

    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(updateSize);
      observer.observe(element);
    }

    window.addEventListener('resize', updateSize);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', updateSize);
    };
  }, [players.length]);

  const getPlayerIndex = (sid: string) => players.findIndex((p) => p.sid === sid);

  const hasSize = size.width > 0 && size.height > 0;
  const hasVotes = voteCounts && Object.keys(voteCounts).length > 0;

  const centerX = center?.pixel?.x ?? size.width / 2;
  const centerY = center?.pixel?.y ?? size.height / 2;
  const minDim = Math.min(size.width, size.height);
  const computedSeatRadius = Math.min(300, Math.max(180, minDim / 2 - 100));
  const finalSeatRadius = typeof seatRadius === 'number' && Number.isFinite(seatRadius)
    ? seatRadius
    : computedSeatRadius;
  const ringCore = isAgent ? 'rgba(245, 158, 11, 0.75)' : 'rgba(245, 158, 11, 0.7)';
  const ringGlow = isAgent ? 'rgba(245, 158, 11, 0.25)' : 'rgba(245, 158, 11, 0.22)';
  const ringRadius = 48;

  return (
    <div ref={containerRef} className="absolute inset-0 w-full h-full pointer-events-none z-10">
      <svg className="absolute inset-0 w-full h-full">
      {hasVotes && hasSize && (() => {
        const entries = Object.entries(voteCounts || {})
          .map(([target, count]) => ({ target, count: Number(count) || 0 }))
          .filter((entry) => entry.count > 0);
        if (entries.length === 0) return null;
        const maxCount = Math.max(...entries.map((entry) => entry.count));
        const topTargets = entries.filter((entry) => entry.count === maxCount).map((entry) => entry.target);
        return topTargets.map((targetSid) => {
          const targetIdx = getPlayerIndex(String(targetSid));
          if (targetIdx === -1) return null;
          const pos = getWerewolfSeatPosition(targetIdx, players.length, finalSeatRadius);
          const cx = centerX + pos.x;
          const cy = centerY + pos.y;
          return (
            <g key={`vote-highlight-${targetSid}`}>
              <motion.circle
                initial={{ opacity: 0, r: ringRadius - 6 }}
                animate={{ opacity: 1, r: ringRadius }}
                transition={{ duration: 0.35 }}
                cx={cx}
                cy={cy}
                r={ringRadius}
                stroke={ringGlow}
                strokeWidth="10"
                fill="none"
              />
              <motion.circle
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.35 }}
                cx={cx}
                cy={cy}
                r={ringRadius}
                stroke={ringCore}
                strokeWidth="2.5"
                fill="none"
              />
            </g>
          );
        });
      })()}
      </svg>
    </div>
  );
}

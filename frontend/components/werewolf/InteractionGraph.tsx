'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { getWerewolfSeatPosition } from './layoutUtils';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';

interface InteractionGraphProps {
  votes: Record<string, string>; // voter_sid -> target_sid
  players: { sid: string }[];
  center?: AnchoredCenter;
  isAgent?: boolean;
}

export default function InteractionGraph({ votes, players, center, isAgent = true }: InteractionGraphProps) {
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
  const hasVotes = Object.keys(votes || {}).length > 0;

  const centerX = center?.pixel?.x ?? size.width / 2;
  const centerY = center?.pixel?.y ?? size.height / 2;
  const minDim = Math.min(size.width, size.height);
  const seatRadius = Math.min(300, Math.max(180, minDim / 2 - 100));
  const lineRadius = Math.max(160, seatRadius - 60);

  const arrowColor = isAgent ? '#ef4444' : 'rgb(244, 63, 94)';
  const arrowOpacity = isAgent ? 1 : 0.6;
  const markerId = isAgent ? 'arrowhead-agent' : 'arrowhead-human';

  return (
    <div ref={containerRef} className="absolute inset-0 w-full h-full pointer-events-none z-10">
      <svg className="absolute inset-0 w-full h-full">
      <defs>
        <marker
          id={markerId}
          markerWidth="10"
          markerHeight="7"
          refX="9"
          refY="3.5"
          orient="auto"
        >
          <polygon points="0 0, 10 3.5, 0 7" fill={arrowColor} fillOpacity={arrowOpacity} />
        </marker>
      </defs>
      {hasVotes && hasSize && Object.entries(votes).map(([voterSid, targetSid]) => {
        const voterIdx = getPlayerIndex(voterSid);
        const targetIdx = getPlayerIndex(targetSid);

        if (voterIdx === -1 || targetIdx === -1) return null;

        const start = getWerewolfSeatPosition(voterIdx, players.length, lineRadius);
        const end = getWerewolfSeatPosition(targetIdx, players.length, lineRadius);

        return (
          <motion.line
            key={`${voterSid}-${targetSid}`}
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 0.5 }}
            x1={centerX + start.x}
            y1={centerY + start.y}
            x2={centerX + end.x}
            y2={centerY + end.y}
            stroke={arrowColor}
            strokeOpacity={arrowOpacity}
            strokeWidth="2"
            markerEnd={`url(#${markerId})`}
            strokeDasharray="5,5"
          />
        );
      })}
      </svg>
    </div>
  );
}

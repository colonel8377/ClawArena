'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { getWerewolfSeatPosition } from './layoutUtils';

interface InteractionGraphProps {
  votes: Record<string, string>; // voter_sid -> target_sid
  players: { sid: string }[];
}

export default function InteractionGraph({ votes, players }: InteractionGraphProps) {
  if (!votes || Object.keys(votes).length === 0) return null;

  const getPlayerIndex = (sid: string) => players.findIndex((p) => p.sid === sid);

  return (
    <svg className="absolute inset-0 w-full h-full pointer-events-none z-10">
      <defs>
        <marker
          id="arrowhead"
          markerWidth="10"
          markerHeight="7"
          refX="9"
          refY="3.5"
          orient="auto"
        >
          <polygon points="0 0, 10 3.5, 0 7" fill="#ef4444" />
        </marker>
      </defs>
      {Object.entries(votes).map(([voterSid, targetSid]) => {
        const voterIdx = getPlayerIndex(voterSid);
        const targetIdx = getPlayerIndex(targetSid);
        
        if (voterIdx === -1 || targetIdx === -1) return null;

        const start = getWerewolfSeatPosition(voterIdx, players.length, 35); // Start slightly inside player circle
        const end = getWerewolfSeatPosition(targetIdx, players.length, 35); // End slightly inside player circle

        return (
          <motion.line
            key={`${voterSid}-${targetSid}`}
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 0.5 }}
            x1={`${start.rawX}%`}
            y1={`${start.rawY}%`}
            x2={`${end.rawX}%`}
            y2={`${end.rawY}%`}
            stroke="#ef4444"
            strokeWidth="2"
            markerEnd="url(#arrowhead)"
            strokeDasharray="5,5"
          />
        );
      })}
    </svg>
  );
}

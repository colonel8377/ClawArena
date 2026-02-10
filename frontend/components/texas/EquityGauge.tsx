'use client';

import React from 'react';
import { SpectatorPlayer } from '@/store/types';

interface EquityGaugeProps {
  cards: string[]; // Hole cards
  communityCards: string[];
}

// Simple lookup for pair/suited connectors if we don't use a solver
// Since we cannot change backend, and solving on frontend is heavy, we just show "Hand Type"
export default function EquityGauge({ cards, communityCards }: EquityGaugeProps) {
  if (!cards || cards.length !== 2) return null;

  // Placeholder for "Real Equity" - just checking if pair or suited
  const isPair = cards[0][0] === cards[1][0];
  const isSuited = cards[0][1] === cards[1][1];
  
  // Calculate approximate strength (very basic heuristic)
  let label = "High Card";
  let color = "text-gray-500";
  
  if (isPair) {
    label = "Pocket Pair";
    color = "text-yellow-400";
  } else if (isSuited) {
    label = "Suited";
    color = "text-blue-400";
  }

  return (
    <div className="absolute -bottom-6 left-1/2 -translate-x-1/2 bg-black/80 px-2 py-0.5 rounded text-[10px] whitespace-nowrap border border-gray-700">
      <span className={color}>{label}</span>
      {/* If we had backend equity, we would show: <span className="ml-1 text-white">34%</span> */}
    </div>
  );
}

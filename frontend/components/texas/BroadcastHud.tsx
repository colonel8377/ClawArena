'use client';

import React from 'react';
import { useUiMode } from '@/components/UiModeProvider';

interface BroadcastHudProps {
  phase?: string;
  currentPlayerName?: string;
  turnRemainingMs?: number | null;
}

export default function BroadcastHud({
  phase,
  currentPlayerName,
  turnRemainingMs,
}: BroadcastHudProps) {
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';
  const phaseLabel = phase ? phase.replace(/_/g, ' ') : 'Unknown';
  const turnLabel = currentPlayerName ? `${currentPlayerName} to act` : 'Waiting for action';
  const timerLabel = turnRemainingMs !== null && turnRemainingMs !== undefined ? `(${Math.ceil(turnRemainingMs / 1000)}s)` : '';

  return (
    <div className={`px-5 py-2 rounded-full border backdrop-blur-md shadow-lg ${
      isAgent
        ? 'bg-black/70 border-emerald-400/30 text-emerald-100'
        : 'bg-white/90 border-emerald-200 text-emerald-700'
    }`}>
      <div className="text-xs font-black uppercase tracking-[0.35em] text-center">
        {phaseLabel.toUpperCase()}
      </div>
      <div className="mt-1 text-xs font-semibold tracking-wide text-center">
        {turnLabel} {timerLabel}
      </div>
    </div>
  );
}

'use client';

import React from 'react';
import { useUiMode } from '@/components/UiModeProvider';

interface EventTickerProps {
  message?: string | null;
  tone?: 'action' | 'win' | 'system';
}

export default function EventTicker({ message, tone = 'action' }: EventTickerProps) {
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';

  if (!message) return null;

  const toneClass = tone === 'win'
    ? (isAgent ? 'bg-emerald-500/20 text-emerald-100 border-emerald-400/40' : 'bg-emerald-100 text-emerald-700 border-emerald-200')
    : tone === 'system'
      ? (isAgent ? 'bg-purple-500/20 text-purple-100 border-purple-400/40' : 'bg-purple-100 text-purple-700 border-purple-200')
      : (isAgent ? 'bg-black/70 text-emerald-100 border-emerald-400/30' : 'bg-white/90 text-emerald-700 border-emerald-200');

  return (
    <div className="absolute left-0 right-0 top-6 z-40 pointer-events-none flex justify-center">
      <div
        className={`px-5 py-2 rounded-full border shadow-xl backdrop-blur-md text-sm font-semibold tracking-wide text-center whitespace-nowrap overflow-hidden text-ellipsis w-[360px] max-w-[80vw] ${toneClass}`}
      >
        {message}
      </div>
    </div>
  );
}

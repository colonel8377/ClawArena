'use client';

import React from 'react';
import { useUiMode } from '@/components/UiModeProvider';

interface EconomyBarProps {
  pot?: number;
  smallBlind?: number;
  bigBlind?: number;
}

export default function EconomyBar({ pot, smallBlind, bigBlind }: EconomyBarProps) {
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';

  return (
    <div className="absolute left-0 right-0 bottom-6 flex justify-center z-30 pointer-events-none">
      <div className={`flex items-center gap-4 px-5 py-2 rounded-full border backdrop-blur-md shadow-lg ${
        isAgent
          ? 'bg-black/70 border-emerald-400/30 text-emerald-100'
          : 'bg-white/90 border-emerald-200 text-emerald-700'
      }`}>
        <div className="text-xs font-semibold tracking-wide">
          POT: <span className="font-black">🪙{pot ?? 0}</span>
        </div>
        {(smallBlind && bigBlind) && (
          <div className="text-xs font-semibold tracking-wide">
            BLINDS: <span className="font-black">{smallBlind}🪙/{bigBlind}🪙</span>
          </div>
        )}
        <div className="text-[11px] uppercase tracking-widest text-emerald-200/80">
          1 token = 10 🪙
        </div>
      </div>
    </div>
  );
}

'use client';

import React from 'react';

export type Suit = 'hearts' | 'diamonds' | 'clubs' | 'spades';
export type Rank = 'A' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '10' | 'J' | 'Q' | 'K';

interface PlayingCardProps {
  suit: Suit;
  rank: Rank;
  hidden?: boolean;
  className?: string;
}

const PlayingCard: React.FC<PlayingCardProps> = ({ suit, rank, hidden = false, className = '' }) => {
  // Get suit symbol
  const getSuitSymbol = (suit: Suit): string => {
    switch (suit) {
      case 'hearts': return '♥';
      case 'diamonds': return '♦';
      case 'clubs': return '♣';
      case 'spades': return '♠';
    }
  };

  // Get suit color
  const getSuitColor = (suit: Suit): string => {
    if (suit === 'hearts' || suit === 'diamonds') {
      return 'text-red-600';
    }
    return 'text-slate-800';
  };

  const getSuitTextShadow = (suit: Suit): string => {
    if (suit === 'hearts' || suit === 'diamonds') {
      return 'drop-shadow-[0_1px_0_rgba(255,255,255,0.2)]';
    }
    return 'drop-shadow-[0_1px_0_rgba(255,255,255,0.25)]';
  };

  const getBorderColor = (suit: Suit): string => {
    if (suit === 'hearts' || suit === 'diamonds') {
      return 'border-red-200';
    }
    return 'border-slate-200';
  };

  if (hidden) {
    return (
      <div
        className={`
          relative w-20 h-28 
          bg-slate-900 border-2 border-slate-700
          rounded-lg overflow-hidden
          shadow-lg
          ${className}
        `}
        role="img"
        aria-label="Hidden playing card"
      >
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-5xl opacity-70">🃏</div>
        </div>
        <div className="absolute inset-0 bg-gradient-to-br from-slate-800/70 via-transparent to-slate-900/70" />
      </div>
    );
  }

  return (
    <div
      className={`
        relative w-20 h-28 
        bg-white border-2 ${getBorderColor(suit)}
        rounded-lg overflow-hidden
        shadow-md
        transition-transform hover:scale-[1.03]
        ${className}
      `}
      role="img"
      aria-label={`${rank} of ${suit}`}
    >
      <div className="absolute inset-0 flex items-center justify-center text-6xl opacity-5 select-none">
        🃏
      </div>
      
      {/* Card content */}
      <div className="relative h-full flex flex-col p-2">
        {/* Top rank and suit */}
        <div className="flex flex-col items-start">
          <div className={`text-[15px] font-bold leading-none tracking-tight ${getSuitColor(suit)} ${getSuitTextShadow(suit)}`}>
            {rank}
          </div>
          <div className={`text-xl ${getSuitColor(suit)} leading-none`}>
            {getSuitSymbol(suit)}
          </div>
        </div>
        
        {/* Center suit symbol (consistent for all ranks) */}
        <div className="flex-1 flex items-center justify-center">
          <div className={`text-3xl ${getSuitColor(suit)} ${getSuitTextShadow(suit)}`}>
            {getSuitSymbol(suit)}
          </div>
        </div>
        
        {/* Bottom rank and suit (rotated) */}
        <div className="flex flex-col items-end rotate-180">
          <div className={`text-[15px] font-bold leading-none tracking-tight ${getSuitColor(suit)} ${getSuitTextShadow(suit)}`}>
            {rank}
          </div>
          <div className={`text-xl ${getSuitColor(suit)} leading-none`}>
            {getSuitSymbol(suit)}
          </div>
        </div>
      </div>
      
      {/* Corner accents */}
      {(() => {
        const borderColorClass = getBorderColor(suit).split(' ')[0];
        return (
          <>
            <div className={`absolute top-0 left-0 w-2 h-2 border-l-2 border-t-2 ${borderColorClass} opacity-50`}></div>
            <div className={`absolute top-0 right-0 w-2 h-2 border-r-2 border-t-2 ${borderColorClass} opacity-50`}></div>
            <div className={`absolute bottom-0 left-0 w-2 h-2 border-l-2 border-b-2 ${borderColorClass} opacity-50`}></div>
            <div className={`absolute bottom-0 right-0 w-2 h-2 border-r-2 border-b-2 ${borderColorClass} opacity-50`}></div>
          </>
        );
      })()}
    </div>
  );
};

export default PlayingCard;

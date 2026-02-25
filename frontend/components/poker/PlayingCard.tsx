'use client';

import React from 'react';

export type Suit = 'hearts' | 'diamonds' | 'clubs' | 'spades';
export type Rank = 'A' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '10' | 'J' | 'Q' | 'K';

interface PlayingCardProps {
  suit: Suit;
  rank: Rank;
  hidden?: boolean;
  compact?: boolean;
  showRank?: boolean;
  className?: string;
}

const PlayingCard: React.FC<PlayingCardProps> = ({ suit, rank, hidden = false, compact = false, showRank = true, className = '' }) => {
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
      return 'text-red-700';
    }
    return 'text-slate-900';
  };

  const getSuitTextShadow = (suit: Suit): string => {
    if (suit === 'hearts' || suit === 'diamonds') {
      return 'drop-shadow-[0_1px_0_rgba(255,255,255,0.2)]';
    }
    return 'drop-shadow-[0_1px_0_rgba(255,255,255,0.25)]';
  };

  const getBorderColor = (_suit: Suit): string => 'border-slate-200';

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
        bg-[#f7f6f2] border-2 ${getBorderColor(suit)}
        rounded-lg overflow-hidden
        shadow-[0_6px_16px_rgba(0,0,0,0.25)]
        ring-1 ring-black/5
        ${className}
      `}
      role="img"
      aria-label="Playing card"
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.9),rgba(255,255,255,0.4)_45%,rgba(0,0,0,0.02)_100%)]" />
      <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.55),rgba(0,0,0,0.03))]" />
      
      {/* Card content */}
      <div
        className="relative h-full font-serif"
        style={{ fontFamily: '"Times New Roman", "Georgia", serif' }}
      >
        {/* Top-left rank and suit */}
        <div className="absolute top-2 left-2 flex flex-col items-start leading-none">
          {showRank && (
            <div className={`${compact ? 'text-[13px]' : 'text-[20px]'} font-bold tracking-tight ${getSuitColor(suit)} ${getSuitTextShadow(suit)}`}>
              {rank}
            </div>
          )}
          <div className={`${compact ? 'text-[14px]' : 'text-[20px]'} ${getSuitColor(suit)} leading-none`}>
            {getSuitSymbol(suit)}
          </div>
        </div>
        
        {/* Center suit symbol (consistent for all ranks) */}
        {!compact && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className={`text-5xl ${getSuitColor(suit)} ${getSuitTextShadow(suit)}`}>
              {getSuitSymbol(suit)}
            </div>
          </div>
        )}
        
        {/* Bottom-right rank and suit (rotated) */}
        <div className="absolute bottom-2 right-2 flex flex-col items-end rotate-180 leading-none">
          {showRank && (
            <div className={`${compact ? 'text-[13px]' : 'text-[20px]'} font-bold tracking-tight ${getSuitColor(suit)} ${getSuitTextShadow(suit)}`}>
              {rank}
            </div>
          )}
          <div className={`${compact ? 'text-[14px]' : 'text-[20px]'} ${getSuitColor(suit)} leading-none`}>
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

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

  // Get suit color and glow
  const getSuitColor = (suit: Suit): string => {
    if (suit === 'hearts' || suit === 'diamonds') {
      return 'text-neonPink';
    }
    return 'text-cyberBlue';
  };

  const getSuitGlow = (suit: Suit): string => {
    if (suit === 'hearts' || suit === 'diamonds') {
      return 'shadow-neon-pink';
    }
    return 'shadow-neon-blue';
  };

  const getBorderColor = (suit: Suit): string => {
    if (suit === 'hearts' || suit === 'diamonds') {
      return 'border-neonPink neon-glow-pink';
    }
    return 'border-cyberBlue neon-glow-blue';
  };

  // Check if it's a face card for holographic effect
  const isFaceCard = rank === 'J' || rank === 'Q' || rank === 'K';

  if (hidden) {
    return (
      <div
        className={`
          relative w-20 h-28 
          bg-backgroundSlate border-2 border-electricPurple
          rounded-lg overflow-hidden
          shadow-neon-purple
          ${className}
        `}
      >
        {/* Circuit board pattern background */}
        <div className="absolute inset-0 circuit-pattern opacity-30"></div>
        
        {/* Central design */}
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-electricPurple text-3xl font-bold opacity-50">?</div>
        </div>
        
        {/* Animated lines */}
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-electricPurple pulse-glow"></div>
        <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-electricPurple pulse-glow"></div>
      </div>
    );
  }

  return (
    <div
      className={`
        relative w-20 h-28 
        bg-backgroundSlate/80 border-2 ${getBorderColor(suit)}
        rounded-lg overflow-hidden
        ${getSuitGlow(suit)}
        transition-transform hover:scale-105 hover:rotate-2
        ${className}
      `}
    >
      {/* Holographic effect for face cards */}
      {isFaceCard && (
        <div className="absolute inset-0 holographic opacity-10"></div>
      )}
      
      {/* Card content */}
      <div className="relative h-full flex flex-col p-2">
        {/* Top rank and suit */}
        <div className="flex flex-col items-start">
          <div className={`text-lg font-bold ${getSuitColor(suit)} text-shadow-neon-blue`}>
            {rank}
          </div>
          <div className={`text-2xl ${getSuitColor(suit)} leading-none`}>
            {getSuitSymbol(suit)}
          </div>
        </div>
        
        {/* Center suit symbol */}
        <div className="flex-1 flex items-center justify-center">
          <div className={`text-4xl ${getSuitColor(suit)} ${isFaceCard ? 'font-orbitron' : ''}`}>
            {isFaceCard ? rank : getSuitSymbol(suit)}
          </div>
        </div>
        
        {/* Bottom rank and suit (rotated) */}
        <div className="flex flex-col items-end rotate-180">
          <div className={`text-lg font-bold ${getSuitColor(suit)} text-shadow-neon-blue`}>
            {rank}
          </div>
          <div className={`text-2xl ${getSuitColor(suit)} leading-none`}>
            {getSuitSymbol(suit)}
          </div>
        </div>
      </div>
      
      {/* Corner accents */}
      <div className="absolute top-0 left-0 w-2 h-2 border-l-2 border-t-2 border-current opacity-50"></div>
      <div className="absolute top-0 right-0 w-2 h-2 border-r-2 border-t-2 border-current opacity-50"></div>
      <div className="absolute bottom-0 left-0 w-2 h-2 border-l-2 border-b-2 border-current opacity-50"></div>
      <div className="absolute bottom-0 right-0 w-2 h-2 border-r-2 border-b-2 border-current opacity-50"></div>
    </div>
  );
};

export default PlayingCard;

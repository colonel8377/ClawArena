'use client';

import React from 'react';
import { clsx } from 'clsx';

interface DayNightCycleProps {
  phase: string;
  children: React.ReactNode;
}

export default function DayNightCycle({ phase, children }: DayNightCycleProps) {
  const isNight = phase.includes('night');
  
  return (
    <div className={clsx(
      "relative w-full h-full transition-colors duration-[2000ms] overflow-hidden",
      isNight ? "bg-[#050510]" : "bg-[#1a1a2e]" // Night vs Day (Dark vs Slightly Lighter Dark for "Geek" theme)
    )}>
      {/* Ambient Light Effect */}
      <div className={clsx(
        "absolute inset-0 pointer-events-none transition-opacity duration-[2000ms]",
        isNight ? "opacity-40 bg-blue-900/20 mix-blend-overlay" : "opacity-10 bg-yellow-500/10 mix-blend-overlay"
      )} />
      
      {/* Content */}
      <div className="relative z-10 w-full h-full">
        {children}
      </div>
    </div>
  );
}

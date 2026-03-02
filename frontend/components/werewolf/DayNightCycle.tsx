'use client';

import React from 'react';
import { clsx } from 'clsx';

interface DayNightCycleProps {
  phase: string;
  children: React.ReactNode;
  contentRef?: React.Ref<HTMLDivElement>;
  isAgent?: boolean;
}

export default function DayNightCycle({ phase, children, contentRef, isAgent = true }: DayNightCycleProps) {
  const isNight = phase.includes('night');

  const bgClass = isAgent
    ? (isNight ? 'bg-[#050a08]' : 'bg-[#102018]')
    : (isNight ? 'bg-slate-800' : 'bg-gradient-to-b from-sky-100 to-blue-50');

  const ambientClass = isAgent
    ? (isNight
        ? 'opacity-35 bg-emerald-900/20 mix-blend-overlay'
        : 'opacity-12 bg-emerald-500/10 mix-blend-overlay')
    : (isNight
        ? 'opacity-30 bg-indigo-900/20 mix-blend-overlay'
        : 'opacity-10 bg-amber-200/20 mix-blend-overlay');

  return (
    <div className={clsx(
      "relative w-full h-full transition-colors duration-[2000ms] overflow-hidden",
      bgClass
    )}>
      {/* Ambient Light Effect */}
      <div className={clsx(
        "absolute inset-0 pointer-events-none transition-opacity duration-[2000ms]",
        ambientClass
      )} />

      {/* Content */}
      <div ref={contentRef} className="relative z-10 w-full h-full">
        {children}
      </div>
    </div>
  );
}

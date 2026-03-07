'use client';

import React from 'react';
import Link from 'next/link';
import { useUiMode } from '@/components/UiModeProvider';
import { Sun, Terminal as TerminalIcon, Cpu, Waves } from 'lucide-react';

export default function Header() {
  const { readingMode, setReadingMode } = useUiMode();
  const isAgent = readingMode === 'agent';

  return (
    <header className={`w-full py-6 transition-colors duration-500 border-b ${
      isAgent ? 'bg-black border-gray-800' : 'bg-white/80 backdrop-blur-md border-blue-100'
    }`}>
      <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row justify-between items-center gap-6">
        {/* Logo */}
        <Link href="/" className="group">
          <div className="flex items-center gap-3">
            <div className={`text-2xl font-black tracking-tighter flex items-center gap-2 ${
              isAgent ? 'text-white' : 'text-blue-900'
            }`}>
              {isAgent ? <Cpu className="text-green-500 animate-pulse" /> : <Waves className="text-blue-500" />}
              CLAW ARENA
            </div>
            <span className={`text-xs px-2 py-0.5 rounded-full border ${
              isAgent 
                ? 'border-green-900/50 bg-green-900/20 text-green-500' 
                : 'border-blue-200 bg-blue-50 text-blue-600'
            }`}>
              BETA
            </span>
          </div>
        </Link>

        {/* Human/Agent Tabs (Moltbook Style) */}
        <div className={`p-1 rounded-full flex relative ${
          isAgent ? 'bg-gray-900 border border-gray-800' : 'bg-slate-100/50 border border-slate-200'
        }`}>
          <button
            onClick={() => setReadingMode('human')}
            className={`relative z-10 px-6 py-2.5 rounded-full text-sm font-bold transition-all duration-300 flex items-center gap-2 ${
              !isAgent 
                ? 'bg-white text-blue-600 shadow-md ring-1 ring-black/5' 
                : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/50'
            }`}
          >
            <Sun size={16} className={!isAgent ? "text-orange-500" : ""} />
            I am a Human
          </button>
          <button
            onClick={() => setReadingMode('agent')}
            className={`relative z-10 px-6 py-2.5 rounded-full text-sm font-bold transition-all duration-300 flex items-center gap-2 ${
              isAgent 
                ? 'bg-gray-800 text-green-400 shadow-md ring-1 ring-white/5' 
                : 'text-slate-400 hover:text-slate-600 hover:bg-white/50'
            }`}
          >
            <TerminalIcon size={16} className={isAgent ? "text-green-500" : ""} />
            I am an Agent
          </button>
        </div>
      </div>
    </header>
  );
}

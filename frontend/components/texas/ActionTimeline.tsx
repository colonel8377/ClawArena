'use client';

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useTexasStore } from '@/store/texasStore';
import { useUiMode } from '@/components/UiModeProvider';

export default function ActionTimeline() {
  const logs = useTexasStore((state) => state.gameLog);
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';

  return (
    <div className={`h-full flex flex-col backdrop-blur-sm ${
      isAgent ? 'bg-black/40 border-l border-green-900/30' : 'bg-white/50 border-l border-slate-200'
    }`}>
      <div className={`p-3 border-b ${
        isAgent ? 'border-green-900/30' : 'border-slate-100'
      }`}>
        <h3 className={`text-xs font-bold uppercase tracking-widest ${
          isAgent ? 'font-mono text-green-400' : 'font-sans text-slate-700'
        }`}>Live Action</h3>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-2 scrollbar-thin scrollbar-thumb-gray-400 scrollbar-track-transparent">
        <AnimatePresence initial={false}>
          {[...logs].reverse().map((log, i) => (
            <motion.div
              layout
              key={`${i}-${log.substring(0, 10)}`}
              initial={{ opacity: 0, x: -20, height: 0 }}
              animate={{ opacity: 1, x: 0, height: 'auto' }}
              className={`text-xs ${isAgent ? 'font-mono' : 'font-sans'}`}
            >
              <span className={`mr-2 ${isAgent ? 'text-green-600' : 'text-slate-400'}`}>
                [{new Date().toLocaleTimeString().split(' ')[0]}]
              </span>
              <span className={isAgent ? 'text-green-300' : 'text-slate-700 font-medium'}>
                {log}
              </span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

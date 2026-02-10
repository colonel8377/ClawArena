'use client';

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useTexasStore } from '@/store/texasStore';

export default function ActionTimeline() {
  const logs = useTexasStore((state) => state.gameLog);

  return (
    <div className="h-full flex flex-col bg-black/40 border-l border-green-900/30 backdrop-blur-sm">
      <div className="p-3 border-b border-green-900/30">
        <h3 className="text-xs font-mono text-green-400 uppercase tracking-widest">Live Action</h3>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-2 scrollbar-thin scrollbar-thumb-green-900 scrollbar-track-transparent">
        <AnimatePresence initial={false}>
          {[...logs].reverse().map((log, i) => (
            <motion.div
              key={`${i}-${log.substring(0, 10)}`}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              className="text-xs font-mono"
            >
              <span className="text-green-600 mr-2">[{new Date().toLocaleTimeString().split(' ')[0]}]</span>
              <span className="text-green-300">{log}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

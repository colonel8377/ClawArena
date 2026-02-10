'use client';

import React from 'react';
import { useParams } from 'next/navigation';
import { useSpectatorSocket } from '@/hooks/useSpectatorSocket';
import { useWerewolfStore } from '@/store/werewolfStore';
import { useUiMode } from '@/components/UiModeProvider';
import DayNightCycle from '@/components/werewolf/DayNightCycle';
import GodViewBoard from '@/components/werewolf/GodViewBoard';
import InteractionGraph from '@/components/werewolf/InteractionGraph';
import { motion, AnimatePresence } from 'framer-motion';

export default function WerewolfGamePage() {
  const { gameId } = useParams() as { gameId: string };
  const { readingMode } = useUiMode();
  
  const { 
    gameState, 
    setGameState, 
    addAction,
    actionTimeline,
    setConnected
  } = useWerewolfStore();

  useSpectatorSocket({
    namespace: 'werewolf',
    tableId: gameId,
    revealMode: readingMode === 'human',
    events: {
      game_state: (data) => setGameState(data),
      werewolf_state: (data) => setGameState(data),
      connect: () => setConnected(true),
      disconnect: () => setConnected(false),
      // If backend sends specific action events, bind them here.
      // Based on search results, 'werewolf_vote', 'werewolf_night_action' might be useful
      // But 'game_state' seems to contain most info including last_action or action logs
    }
  });

  if (!gameState) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-black text-purple-500 font-mono">
        <div className="animate-pulse">SYNCHRONIZING NEURAL LINK...</div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-black text-gray-200 font-mono">
      <div className="flex-1 relative">
        <DayNightCycle phase={gameState.phase}>
           {/* Center Info */}
           <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-center pointer-events-none opacity-20">
             <div className="text-8xl font-black tracking-widest text-white">WOLF</div>
             <div className="text-xl tracking-[1em] text-white mt-4">{gameState.phase.toUpperCase().replace('_', ' ')}</div>
             <div className="text-sm mt-2">DAY {gameState.day_count}</div>
           </div>

           {/* Visualization */}
           <GodViewBoard players={gameState.players} />
           <InteractionGraph votes={gameState.votes || {}} players={gameState.players} />
        </DayNightCycle>
      </div>

      {/* Sidebar Timeline */}
      <div className="w-80 border-l border-gray-800 bg-black/90 z-30 flex flex-col">
        <div className="p-4 border-b border-gray-800">
          <h2 className="text-sm font-bold text-purple-400">EVENT LOG</h2>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {/* Chat Messages as Timeline for now, since ActionTimeline relies on events we might not fully have */}
          {gameState.chat_messages?.slice().reverse().map((msg, i) => (
             <motion.div 
               key={i} 
               initial={{ opacity: 0, x: 20 }}
               animate={{ opacity: 1, x: 0 }}
               className="text-xs border-l-2 border-gray-700 pl-2 py-1"
             >
               <div className="flex justify-between text-gray-500 mb-1">
                 <span>{msg.nickname}</span>
                 <span>{msg.timestamp || ''}</span>
               </div>
               <div className="text-gray-300">{msg.message}</div>
             </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}

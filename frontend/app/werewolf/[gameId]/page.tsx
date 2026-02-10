'use client';

import React from 'react';
import { useParams } from 'next/navigation';
import { useSpectatorSocket } from '@/hooks/useSpectatorSocket';
import { useWerewolfStore } from '@/store/werewolfStore';
import { useUiMode } from '@/components/UiModeProvider';
import DayNightCycle from '@/components/werewolf/DayNightCycle';
import GodViewBoard from '@/components/werewolf/GodViewBoard';
import InteractionGraph from '@/components/werewolf/InteractionGraph';
import { motion } from 'framer-motion';

export default function WerewolfGamePage() {
  const { gameId } = useParams() as { gameId: string };
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';
  
  const { 
    gameState, 
    setGameState, 
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
      <div className={`min-h-screen flex items-center justify-center font-mono ${
        isAgent ? 'bg-black text-purple-500' : 'bg-slate-50 text-slate-500'
      }`}>
        <div className="animate-pulse flex flex-col items-center gap-4">
          {isAgent ? (
            <>
              <div className="text-4xl">🦞</div>
              <div>SYNCHRONIZING NEURAL LINK...</div>
            </>
          ) : (
            <>
              <div className="w-12 h-12 border-4 border-slate-200 border-t-purple-500 rounded-full animate-spin"></div>
              <div>Loading game state...</div>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`flex h-screen overflow-hidden font-mono transition-colors duration-500 ${
      isAgent ? 'bg-black text-gray-200' : 'bg-slate-50 text-slate-800'
    }`}>
      <div className="flex-1 relative">
        <DayNightCycle phase={gameState.phase}>
           {/* Center Info */}
           <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-center pointer-events-none opacity-20">
             <div className={`text-6xl font-black tracking-tighter ${
               isAgent ? 'text-white' : 'text-slate-900'
             }`}>
               CLAW<span className={isAgent ? 'text-gray-500' : 'text-slate-400'}>ARENA</span>.IO
             </div>
             <div className="text-8xl mt-2">🦞</div>
             <div className={`text-xl tracking-[1em] mt-8 ${
               isAgent ? 'text-white' : 'text-slate-700'
             }`}>{gameState.phase.toUpperCase().replace('_', ' ')}</div>
             <div className={`text-sm mt-2 font-mono ${
               isAgent ? 'text-purple-400' : 'text-purple-600'
             }`}>DAY {gameState.day_count}</div>
           </div>

           {/* Visualization */}
           <GodViewBoard players={gameState.players} />
           <InteractionGraph votes={gameState.votes || {}} players={gameState.players} />
        </DayNightCycle>
      </div>

      {/* Sidebar Timeline */}
      <div className={`w-80 border-l z-30 flex flex-col ${
        isAgent 
          ? 'border-gray-800 bg-black/90' 
          : 'border-slate-200 bg-white/90 backdrop-blur-md shadow-xl'
      }`}>
        <div className={`p-4 border-b ${
          isAgent ? 'border-gray-800' : 'border-slate-100'
        }`}>
          <h2 className={`text-sm font-bold ${
            isAgent ? 'text-purple-400' : 'text-slate-800'
          }`}>
            {isAgent ? 'EVENT LOG' : 'Game Log'}
          </h2>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {/* Chat Messages as Timeline */}
          {gameState.chat_messages?.slice().reverse().map((msg, i) => (
             <motion.div 
               key={i} 
               initial={{ opacity: 0, x: 20 }}
               animate={{ opacity: 1, x: 0 }}
               className={`text-xs border-l-2 pl-2 py-1 ${
                 isAgent 
                   ? 'border-gray-700' 
                   : 'border-slate-200'
               }`}
             >
               <div className={`flex justify-between mb-1 ${
                 isAgent ? 'text-gray-500' : 'text-slate-400'
               }`}>
                 <span className="font-bold">{msg.nickname}</span>
                 <span>{msg.timestamp || ''}</span>
               </div>
               <div className={isAgent ? 'text-gray-300' : 'text-slate-600'}>
                 {msg.message}
               </div>
             </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}

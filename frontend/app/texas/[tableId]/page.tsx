'use client';

import React from 'react';
import { useParams } from 'next/navigation';
import { useSpectatorSocket } from '@/hooks/useSpectatorSocket';
import { useTexasStore } from '@/store/texasStore';
import { useUiMode } from '@/components/UiModeProvider';
import PlayerSeat from '@/components/texas/PlayerSeat';
import CommunityCards from '@/components/texas/CommunityCards';
import ChipStream from '@/components/texas/ChipStream';
import ActionTimeline from '@/components/texas/ActionTimeline';
import { motion } from 'framer-motion';

export default function TexasTablePage() {
  const { tableId } = useParams() as { tableId: string };
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';
  
  const { 
    gameState, 
    setGameState, 
    addLog,
    setConnected
  } = useTexasStore();

  useSpectatorSocket({
    namespace: 'texas',
    tableId,
    revealMode: readingMode === 'human',
    events: {
      game_state: (data) => setGameState(data),
      connect: () => setConnected(true),
      disconnect: () => setConnected(false),
      texas_action: (data) => addLog(`${data.nickname} ${data.action} ${data.amount || ''}`),
      hand_winner: (data) => addLog(`Winner: ${data.winners.join(', ')} (Pot: ${data.amount})`)
    }
  });

  if (!gameState) {
    return (
      <div className={`min-h-screen flex items-center justify-center font-mono ${
        isAgent ? 'bg-black text-green-500' : 'bg-slate-50 text-slate-500'
      }`}>
        <div className="animate-pulse flex flex-col items-center gap-4">
          {isAgent ? (
            <>
              <div className="text-4xl">🦞</div>
              <div>CONNECTING TO SATELLITE...</div>
            </>
          ) : (
            <>
              <div className="w-12 h-12 border-4 border-slate-200 border-t-blue-500 rounded-full animate-spin"></div>
              <div>Loading table...</div>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`flex h-screen overflow-hidden font-mono transition-colors duration-500 ${
      isAgent ? 'bg-[#0a0a0a] text-gray-200' : 'bg-slate-50 text-slate-800'
    }`}>
      {/* Main Game Area */}
      <div className={`flex-1 relative ${
        isAgent 
          ? 'bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-green-900/20 via-black to-black'
          : 'bg-slate-100'
      }`}>
        {/* Table Felt */}
        <div className={`absolute inset-4 m-auto w-[80%] h-[70%] border-[20px] rounded-[200px] shadow-2xl ${
          isAgent
            ? 'border-[#1a1a1a] bg-[#0f2a15] shadow-[inset_0_0_100px_rgba(0,0,0,0.8)]'
            : 'border-[#e2e8f0] bg-[#3b82f6] shadow-[inset_0_0_50px_rgba(0,0,0,0.1)]'
        }`}>
          <div className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-center pointer-events-none select-none z-0 ${
            isAgent ? 'text-green-900/30' : 'text-white/10'
          }`}>
            <div className="text-6xl font-black tracking-tighter opacity-50">
              CLAW<span className={isAgent ? 'text-green-800/40' : 'text-white/20'}>ARENA</span>.IO
            </div>
            <div className="text-9xl mt-4 opacity-20 filter blur-sm">🦞</div>
          </div>
        </div>

        {/* Game Components */}
        <CommunityCards cards={gameState.community_cards || []} />
        
        {/* Pot Display */}
        <motion.div 
          key={gameState.pot}
          initial={{ scale: 1.1 }}
          animate={{ scale: 1 }}
          className="absolute top-[35%] left-1/2 -translate-x-1/2 flex flex-col items-center z-10"
        >
          <div className={`px-4 py-1 rounded-full border font-bold ${
            isAgent 
              ? 'bg-black/60 border-green-800 text-green-400' 
              : 'bg-white/90 border-blue-200 text-blue-600 shadow-lg'
          }`}>
            POT: ${gameState.pot}
          </div>
          {(gameState.small_blind && gameState.big_blind) && (
            <div className={`mt-1 text-[10px] font-mono px-2 py-0.5 rounded ${
              isAgent 
                ? 'text-gray-400 bg-black/40' 
                : 'text-slate-500 bg-white/50'
            }`}>
              Blinds: ${gameState.small_blind}/${gameState.big_blind}
            </div>
          )}
        </motion.div>

        {/* Players */}
        {gameState.players.map((player, idx) => (
          <PlayerSeat 
            key={player.sid} 
            player={player} 
            index={idx} 
            totalPlayers={gameState.players.length}
          />
        ))}

        {/* Animations */}
        <ChipStream 
          players={gameState.players} 
          pot={gameState.pot} 
        />
      </div>

      {/* Sidebar Info */}
      <div className={`w-80 border-l z-30 ${
        isAgent 
          ? 'border-gray-800 bg-black/90' 
          : 'border-slate-200 bg-white/90 backdrop-blur-md shadow-xl'
      }`}>
        <ActionTimeline />
      </div>
    </div>
  );
}

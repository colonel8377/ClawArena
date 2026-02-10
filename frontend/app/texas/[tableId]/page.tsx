'use client';

import React, { useEffect } from 'react';
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
      <div className="min-h-screen flex items-center justify-center bg-black text-green-500 font-mono">
        <div className="animate-pulse">CONNECTING TO SATELLITE...</div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-[#0a0a0a] text-gray-200 overflow-hidden font-mono">
      {/* Main Game Area */}
      <div className="flex-1 relative bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-green-900/20 via-black to-black">
        {/* Table Felt */}
        <div className="absolute inset-4 m-auto w-[80%] h-[70%] border-[20px] border-[#1a1a1a] rounded-[200px] bg-[#0f2a15] shadow-[inset_0_0_100px_rgba(0,0,0,0.8)]">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-green-900/30 text-6xl font-black tracking-widest pointer-events-none select-none">
            CLAW ARENA
          </div>
        </div>

        {/* Game Components */}
        <CommunityCards cards={gameState.community_cards || []} />
        
        {/* Pot Display */}
        <motion.div 
          key={gameState.pot}
          initial={{ scale: 1.1, textShadow: "0 0 10px #22c55e" }}
          animate={{ scale: 1, textShadow: "0 0 0px #22c55e" }}
          className="absolute top-[35%] left-1/2 -translate-x-1/2 flex flex-col items-center z-10"
        >
          <div className="bg-black/60 px-4 py-1 rounded-full border border-green-800 text-green-400 font-bold">
            POT: ${gameState.pot}
          </div>
          {(gameState.small_blind && gameState.big_blind) && (
            <div className="mt-1 text-[10px] text-gray-400 font-mono bg-black/40 px-2 py-0.5 rounded">
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
            communityCards={gameState.community_cards}
            isCurrentTurn={gameState.current_player === player.sid}
            isDealer={gameState.dealer_position === idx}
          />
        ))}

        {/* Animations */}
        <ChipStream 
          players={gameState.players} 
          pot={gameState.pot} 
        />
      </div>

      {/* Sidebar Info */}
      <div className="w-80 border-l border-gray-800 bg-black/90 z-30">
        <ActionTimeline />
      </div>
    </div>
  );
}

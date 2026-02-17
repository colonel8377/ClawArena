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
import getApiBaseUrl from '@/lib/api';
import { botFetch } from '@/lib/antiBot';
import { motion } from 'framer-motion';
import { useAnchoredCenter } from '@/hooks/useAnchoredCenter';

export default function TexasTablePage() {
  const { tableId } = useParams() as { tableId: string };
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';
  const { center: tableCenter, stageRef, anchorRef: tableAnchorRef } = useAnchoredCenter();
  
  const { 
    gameState, 
    setGameState, 
    addLog,
    setConnected,
    reset
  } = useTexasStore();
  const gameLog = useTexasStore((state) => state.gameLog);
  const [loadStatus, setLoadStatus] = React.useState<'loading' | 'ready' | 'ended' | 'error'>('loading');
  const prevPhase = React.useRef<string | undefined>(undefined);
  const prevCurrentPlayer = React.useRef<string | undefined>(undefined);
  const [activeSpeakerSid, setActiveSpeakerSid] = React.useState<string | undefined>(undefined);
  const activeSpeakerTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    // Prevent stale cross-table state from rendering while new snapshot loads.
    reset();
    setLoadStatus('loading');
  }, [tableId, reset]);

  useSpectatorSocket({
    namespace: 'texas',
    tableId,
    revealMode: readingMode === 'human',
    events: {
      game_state: (data) => {
        setGameState(data);
        setLoadStatus('ready');
      },
      TABLE_ABORTED: () => {
        reset();
        setLoadStatus('ended');
      },
      connect: () => setConnected(true),
      disconnect: () => setConnected(false),
      texas_action: (data) => addLog(`${data.nickname} ${data.action} ${data.amount || ''}`),
      hand_winner: (data) => addLog(`Winner: ${data.winners.join(', ')} (Pot: ${data.amount})`)
    }
  });

  React.useEffect(() => {
    let cancelled = false;
    const fetchSnapshot = async () => {
      try {
        const res = await botFetch(`${getApiBaseUrl()}/api/spectate/poker/${tableId}`);
        if (cancelled) return;
        if (res.status === 404) {
          setLoadStatus('ended');
          return;
        }
        if (!res.ok) {
          setLoadStatus('error');
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        setGameState(data);
        setLoadStatus('ready');
      } catch {
        if (!cancelled) {
          setLoadStatus('error');
        }
      }
    };

    fetchSnapshot();
    return () => {
      cancelled = true;
    };
  }, [tableId, setGameState]);

  const isTerminalTable = gameState?.phase === 'finished' || gameState?.phase === 'aborted';

  React.useEffect(() => {
    if (!gameState) return;
    if (prevPhase.current && prevPhase.current !== gameState.phase) {
      addLog(`PHASE: ${gameState.phase.toUpperCase()}`);
    }
    prevPhase.current = gameState.phase;
    if (gameState.current_player && prevCurrentPlayer.current !== gameState.current_player) {
      const current = gameState.players.find((p) => p.sid === gameState.current_player);
      addLog(`TURN: ${current?.nickname || gameState.current_player}`);
      prevCurrentPlayer.current = gameState.current_player;
    }
  }, [gameState, addLog]);

  React.useEffect(() => {
    if (!gameState) return;
    const latestLog = gameLog[gameLog.length - 1];
    if (!latestLog || latestLog.startsWith('PHASE:') || latestLog.startsWith('TURN:') || latestLog.startsWith('Winner:')) return;
    const speaker = gameState.players.find((p) => latestLog.startsWith(p.nickname));
    if (!speaker) return;
    setActiveSpeakerSid(speaker.sid);
    if (activeSpeakerTimer.current) clearTimeout(activeSpeakerTimer.current);
    activeSpeakerTimer.current = setTimeout(() => setActiveSpeakerSid(undefined), 3500);
    return () => {
      if (activeSpeakerTimer.current) clearTimeout(activeSpeakerTimer.current);
    };
  }, [gameLog, gameState]);

  if (isTerminalTable) {
    return (
      <div className={`min-h-screen flex items-center justify-center font-mono ${
        isAgent ? 'bg-black text-green-500' : 'bg-slate-50 text-slate-500'
      }`}>
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="text-4xl">🏁</div>
          <div className="text-lg font-semibold">This game has ended.</div>
          <div className="text-xs opacity-70">Return to the lobby to watch active tables.</div>
        </div>
      </div>
    );
  }

  if (!gameState) {
    if (loadStatus === 'ended') {
      return (
        <div className={`min-h-screen flex items-center justify-center font-mono ${
          isAgent ? 'bg-black text-green-500' : 'bg-slate-50 text-slate-500'
        }`}>
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="text-4xl">🏁</div>
            <div className="text-lg font-semibold">This game has ended.</div>
            <div className="text-xs opacity-70">Return to the lobby to watch active tables.</div>
          </div>
        </div>
      );
    }

    if (loadStatus === 'error') {
      return (
        <div className={`min-h-screen flex items-center justify-center font-mono ${
          isAgent ? 'bg-black text-green-500' : 'bg-slate-50 text-slate-500'
        }`}>
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="text-4xl">⚠️</div>
            <div className="text-lg font-semibold">Unable to load this game.</div>
            <div className="text-xs opacity-70">Please try again later.</div>
          </div>
        </div>
      );
    }

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

  const totalPlayers = gameState.players.length;
  const dealerIndex = Number.isFinite(gameState.dealer_position) ? Number(gameState.dealer_position) : undefined;
  const smallBlindIndex = dealerIndex !== undefined && totalPlayers > 0
    ? (dealerIndex + 1) % totalPlayers
    : undefined;
  const bigBlindIndex = dealerIndex !== undefined && totalPlayers > 0
    ? (dealerIndex + 2) % totalPlayers
    : undefined;
  const hudWidth = 'min(420px, 72vw)';

  return (
    <div className={`flex h-screen overflow-hidden font-mono transition-colors duration-500 ${
      isAgent ? 'bg-[#0a0a0a] text-gray-200' : 'bg-slate-50 text-slate-800'
    }`}>
      {/* Main Game Area */}
      <div ref={stageRef} className={`flex-1 relative ${
        isAgent 
          ? 'bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-green-900/20 via-black to-black'
          : 'bg-slate-100'
      }`}>
        {/* Table Felt */}
        <div className={`absolute inset-4 m-auto w-[82%] h-[72%] border-[18px] rounded-[220px] shadow-2xl ${
          isAgent
            ? 'border-[#1a1a1a] bg-[#0f2a15] shadow-[inset_0_0_100px_rgba(0,0,0,0.8)]'
            : 'border-[#e2e8f0] bg-[#3b82f6] shadow-[inset_0_0_50px_rgba(0,0,0,0.1)]'
        }`}>
          <div
            ref={tableAnchorRef}
            className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-2 h-2 pointer-events-none"
          />
          <div
            className={`absolute inset-0 flex items-center justify-center text-center pointer-events-none select-none z-0 ${
            isAgent ? 'text-green-900/30' : 'text-white/10'
          }`}
          >
            <div className="flex flex-col items-center justify-center">
              <div className="text-5xl md:text-6xl font-black tracking-tighter opacity-50">
                CLAW<span className={isAgent ? 'text-green-800/40' : 'text-white/20'}>ARENA</span>.IO
              </div>
              <div className="text-6xl md:text-7xl mt-4 opacity-25 filter blur-[1px] w-fit mx-auto">🦞</div>
            </div>
          </div>
        </div>

        {/* Game Components */}
        <CommunityCards cards={gameState.community_cards || []} center={tableCenter} />

        {/* Phase HUD */}
        <div className="absolute left-0 right-0 top-8 flex justify-center z-20 pointer-events-none">
          <motion.div
            key={gameState.phase}
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            style={{ width: hudWidth }}
          >
            <div className={`w-full text-center px-6 py-2 rounded-full border text-lg font-black tracking-[0.35em] uppercase ${
              isAgent
                ? 'bg-black/70 border-emerald-400/30 text-emerald-100 shadow-[0_12px_40px_rgba(16,185,129,0.2)]'
                : 'bg-white/90 border-emerald-200 text-emerald-700 shadow-lg'
            }`}>
              {gameState.phase}
            </div>
          </motion.div>
        </div>


        {/* Pot Display */}
        <div
          className="absolute left-0 right-0 flex justify-center z-30"
          style={{ top: 'calc(34% + 140px)' }}
        >
          <motion.div
            key={gameState.pot}
            initial={{ scale: 1.1 }}
            animate={{ scale: 1 }}
            className="flex flex-col items-center"
            style={{ width: hudWidth }}
          >
            <div className={`w-full text-center px-5 py-2.5 rounded-full border text-lg font-bold tracking-wide ${
              isAgent 
                ? 'bg-black/75 border-emerald-400/40 text-emerald-100 shadow-[0_10px_30px_rgba(16,185,129,0.2)]' 
                : 'bg-white/95 border-emerald-200 text-emerald-700 shadow-lg'
            }`}>
              POT ${gameState.pot}
            </div>
            {(gameState.small_blind && gameState.big_blind) && (
              <div className={`mt-2 text-sm font-semibold tracking-wider px-3.5 py-1 rounded-full ${
                isAgent 
                  ? 'text-emerald-200 bg-black/50 border border-emerald-400/30' 
                  : 'text-emerald-700 bg-white/70 border border-emerald-200'
              }`}>
                Blinds: ${gameState.small_blind}/${gameState.big_blind}
              </div>
            )}
          </motion.div>
        </div>

        {/* Players */}
        {gameState.players.map((player, idx) => (
          <PlayerSeat
            key={player.sid}
            player={player}
            index={idx}
            totalPlayers={gameState.players.length}
            center={tableCenter}
            isAgent={isAgent}
            isDealer={dealerIndex === idx}
            isSmallBlind={smallBlindIndex === idx}
            isBigBlind={bigBlindIndex === idx}
            isCurrentTurn={gameState.current_player === player.sid}
            isSpeaking={activeSpeakerSid === player.sid}
            pot={gameState.pot}
            winners={gameState.winners}
          />
        ))}

        {/* Animations */}
        <ChipStream
          players={gameState.players}
          pot={gameState.pot}
          center={tableCenter}
        />
      </div>

      {/* Sidebar Info */}
      <div className={`w-80 border-l z-30 ${
        isAgent 
          ? 'border-gray-800 bg-black/90' 
          : 'border-slate-200 bg-white/90 backdrop-blur-md shadow-xl'
      }`}>
        <ActionTimeline
          logs={gameLog}
          phase={gameState.phase}
          currentPlayerSid={gameState.current_player}
          players={gameState.players}
        />
      </div>
    </div>
  );
}

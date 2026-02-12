'use client';

import React from 'react';
import { useParams } from 'next/navigation';
import { useSpectatorSocket } from '@/hooks/useSpectatorSocket';
import { useWerewolfStore } from '@/store/werewolfStore';
import { ChatMessage, WerewolfPlayer } from '@/store/types';
import { useUiMode } from '@/components/UiModeProvider';
import DayNightCycle from '@/components/werewolf/DayNightCycle';
import GodViewBoard from '@/components/werewolf/GodViewBoard';
import InteractionGraph from '@/components/werewolf/InteractionGraph';
import getApiBaseUrl from '@/lib/api';
import { botFetch } from '@/lib/antiBot';
import { motion } from 'framer-motion';
import { useAnchoredCenter } from '@/hooks/useAnchoredCenter';

const hashString = (value: string) => {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
};

const getPlayerHue = (key: string) => (hashString(key) * 47) % 360;

const getRoleName = (role?: WerewolfPlayer['role']) => {
  if (!role) return undefined;
  if (typeof role === 'string') return role;
  return role.role || role.name || role.type;
};

export default function WerewolfGamePage() {
  const { gameId } = useParams() as { gameId: string };
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';
  const { center: tableCenter, stageRef, anchorRef: lobsterAnchorRef } = useAnchoredCenter();
  
  const {
    gameState,
    setGameState,
    setConnected,
    reset
  } = useWerewolfStore();

  const [loadStatus, setLoadStatus] = React.useState<'loading' | 'ready' | 'ended' | 'error'>('loading');

  // Derived state for current speaker based on recent chat messages
  const [activeMessage, setActiveMessage] = React.useState<{ sid: string; content: string } | undefined>(undefined);
  
  // Local system logs for phase changes and deaths
  const [systemLogs, setSystemLogs] = React.useState<ChatMessage[]>([]);
  const prevPhase = React.useRef<string | undefined>(undefined);
  const prevPlayers = React.useRef<WerewolfPlayer[] | undefined>(undefined);
  const prevEliminated = React.useRef<string | undefined>(undefined);
  const prevWinners = React.useRef<string[] | undefined>(undefined);
  const loggedDeathSids = React.useRef<Set<string>>(new Set());

  React.useEffect(() => {
    if (!gameState) return;
    setLoadStatus('ready');

    const newLogs: ChatMessage[] = [];
    const now = new Date().toISOString();

    // Check Phase Change
    if (prevPhase.current && prevPhase.current !== gameState.phase) {
      newLogs.push({
        nickname: 'SYSTEM',
        message: `--- Phase: ${gameState.phase.replace(/_/g, ' ')} ---`,
        timestamp: now,
        sid: 'system-phase',
        isSystem: true
      });
    }
    prevPhase.current = gameState.phase;

    // Check Deaths — prefer structured deaths array from backend
    if (gameState.deaths && gameState.deaths.length > 0) {
      for (const death of gameState.deaths) {
        if (loggedDeathSids.current.has(death.sid)) continue;
        loggedDeathSids.current.add(death.sid);
        let causeText = 'has been eliminated';
        if (death.cause === 'wolf_kill') causeText = 'was killed by wolves';
        else if (death.cause === 'poison') causeText = 'was poisoned by the witch';
        else if (death.cause === 'vote') causeText = 'was voted out';
        else if (death.cause === 'hunter_shot') causeText = 'was shot by the hunter';
        const roleText = death.role_revealed ? ` (Role: ${death.role_revealed})` : '';
        newLogs.push({
          nickname: 'SYSTEM',
          message: `☠️ ${death.nickname} ${causeText}${roleText}`,
          timestamp: now,
          sid: 'system-death',
          isSystem: true
        });
      }
    }

    // Fallback: detect deaths via player diff (for backends that don't send deaths array)
    if (prevPlayers.current) {
       gameState.players.forEach((p) => {
         if (loggedDeathSids.current.has(p.sid)) return;
         const oldP = prevPlayers.current?.find((op) => op.sid === p.sid);
         if (oldP && oldP.is_alive && !p.is_alive) {
            loggedDeathSids.current.add(p.sid);
            newLogs.push({
                nickname: 'SYSTEM',
                message: `☠️ ${p.nickname} has been eliminated!`,
                timestamp: now,
                sid: 'system-death',
                isSystem: true
            });
         }
       });
    }
    prevPlayers.current = gameState.players;

    if (gameState.eliminated_last_night && gameState.eliminated_last_night !== prevEliminated.current) {
      newLogs.push({
        nickname: 'SYSTEM',
        message: `☠️ ${gameState.eliminated_last_night} was eliminated last night.`,
        timestamp: now,
        sid: 'system-night-death',
        isSystem: true
      });
      prevEliminated.current = gameState.eliminated_last_night;
    }

    if (gameState.winners && gameState.winners.length > 0) {
      const winnersKey = gameState.winners.join('|');
      const prevKey = prevWinners.current?.join('|');
      if (winnersKey !== prevKey) {
        newLogs.push({
          nickname: 'SYSTEM',
          message: `🏆 Winners: ${gameState.winners.join(', ')}`,
          timestamp: now,
          sid: 'system-winners',
          isSystem: true
        });
        prevWinners.current = [...gameState.winners];
      }
    }

    if (newLogs.length > 0) {
      setSystemLogs(prev => [...prev, ...newLogs]);
    }
  }, [gameState]);

  // Merge and sort messages
  const allMessages = React.useMemo(() => {
     const chats = gameState?.chat_messages || [];
     const combined = [...chats, ...systemLogs];
     return combined.sort((a, b) => {
        const tA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
        const tB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
        return tA - tB;
     });
  }, [gameState?.chat_messages, systemLogs]);

  const playerMeta = React.useMemo(() => {
    const map = new Map<string, { nickname: string; role?: string; color: string }>();
    (gameState?.players || []).forEach((p) => {
      const roleName = getRoleName(p.role);
      const hue = getPlayerHue(p.sid || p.nickname);
      map.set(p.sid, {
        nickname: p.nickname,
        role: roleName ? roleName.toUpperCase() : undefined,
        color: `hsl(${hue} 70% ${isAgent ? 65 : 40}%)`
      });
    });
    return map;
  }, [gameState?.players, isAgent]);

  const getSystemLogTone = React.useCallback((sid?: string) => {
    if (!sid) return 'system-default';
    if (sid === 'system-phase') return 'system-phase';
    if (sid === 'system-death') return 'system-death';
    if (sid === 'system-night-death') return 'system-night-death';
    if (sid === 'system-winners') return 'system-winners';
    return 'system-default';
  }, []);

  const systemToneClasses: Record<string, {
    border: string;
    background: string;
    header: string;
    body: string;
  }> = isAgent ? {
    'system-phase': {
      border: 'border-sky-500',
      background: 'bg-sky-500/10',
      header: 'text-sky-500',
      body: 'text-sky-200'
    },
    'system-death': {
      border: 'border-rose-500',
      background: 'bg-rose-500/10',
      header: 'text-rose-500',
      body: 'text-rose-200'
    },
    'system-night-death': {
      border: 'border-orange-500',
      background: 'bg-orange-500/10',
      header: 'text-orange-500',
      body: 'text-orange-200'
    },
    'system-winners': {
      border: 'border-emerald-500',
      background: 'bg-emerald-500/10',
      header: 'text-emerald-500',
      body: 'text-emerald-200'
    },
    'system-default': {
      border: 'border-yellow-500',
      background: 'bg-yellow-500/10',
      header: 'text-yellow-500',
      body: 'text-yellow-200'
    }
  } : {
    'system-phase': {
      border: 'border-sky-300',
      background: 'bg-sky-50',
      header: 'text-sky-600',
      body: 'text-sky-700'
    },
    'system-death': {
      border: 'border-rose-300',
      background: 'bg-rose-50',
      header: 'text-rose-600',
      body: 'text-rose-700'
    },
    'system-night-death': {
      border: 'border-orange-300',
      background: 'bg-orange-50',
      header: 'text-orange-600',
      body: 'text-orange-700'
    },
    'system-winners': {
      border: 'border-emerald-300',
      background: 'bg-emerald-50',
      header: 'text-emerald-600',
      body: 'text-emerald-700'
    },
    'system-default': {
      border: 'border-yellow-300',
      background: 'bg-yellow-50',
      header: 'text-yellow-600',
      body: 'text-yellow-700'
    }
  };

  React.useEffect(() => {
    if (!gameState?.chat_messages?.length) return;
    
    const lastMsg = gameState.chat_messages[gameState.chat_messages.length - 1];
    if (!lastMsg) return;

    // We can just set the speaker to the last message sender for a few seconds
    setActiveMessage({ sid: lastMsg.sid!, content: lastMsg.message });
    
    const timer = setTimeout(() => {
      setActiveMessage(undefined);
    }, 5000); // Highlight for 5 seconds

    return () => clearTimeout(timer);
  }, [gameState?.chat_messages]); // Re-run when chat messages update

  useSpectatorSocket({
    namespace: 'werewolf',
    tableId: gameId,
    revealMode: true, // Always reveal for God View
    events: {
      game_state: (data) => {
        setGameState(data);
        setLoadStatus('ready');
      },
      werewolf_state: (data) => {
        setGameState(data);
        setLoadStatus('ready');
      },
      GAME_ABORTED: () => {
        reset();
        setLoadStatus('ended');
      },
      werewolf_phase_change: (data) => {
        const now = new Date().toISOString();
        const phaseLogs: ChatMessage[] = [];

        // Log deaths from the phase change event
        if (data.deaths && Array.isArray(data.deaths)) {
          for (const death of data.deaths) {
            if (loggedDeathSids.current.has(death.sid)) continue;
            loggedDeathSids.current.add(death.sid);
            let causeText = 'has been eliminated';
            if (death.cause === 'wolf_kill') causeText = 'was killed by wolves';
            else if (death.cause === 'poison') causeText = 'was poisoned by the witch';
            else if (death.cause === 'vote') causeText = 'was voted out';
            else if (death.cause === 'hunter_shot') causeText = 'was shot by the hunter';
            const roleText = death.role_revealed ? ` (Role: ${death.role_revealed})` : '';
            phaseLogs.push({
              nickname: 'SYSTEM',
              message: `☠️ ${death.nickname} ${causeText}${roleText}`,
              timestamp: now,
              sid: 'system-death',
              isSystem: true
            });
          }
        }

        // Log phase transition
        if (data.phase) {
          const dayText = data.day_count ? ` (Day ${data.day_count})` : '';
          phaseLogs.push({
            nickname: 'SYSTEM',
            message: `--- Phase: ${String(data.phase).replace(/_/g, ' ')}${dayText} ---`,
            timestamp: now,
            sid: 'system-phase',
            isSystem: true
          });
        }

        // Log game over / winners
        if (data.winners && Array.isArray(data.winners) && data.winners.length > 0) {
          phaseLogs.push({
            nickname: 'SYSTEM',
            message: `🏆 Winners: ${data.winners.join(', ')}`,
            timestamp: now,
            sid: 'system-winners',
            isSystem: true
          });
        }

        if (phaseLogs.length > 0) {
          setSystemLogs(prev => [...prev, ...phaseLogs]);
        }
      },
      connect: () => setConnected(true),
      disconnect: () => setConnected(false),
    }
  });

  React.useEffect(() => {
    let cancelled = false;
    const fetchSnapshot = async () => {
      try {
        const res = await botFetch(`${getApiBaseUrl()}/api/spectate/werewolf/${gameId}`);
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
  }, [gameId, setGameState]);

  const isTerminalGame = gameState?.phase === 'finished' || gameState?.phase === 'aborted';

  if (isTerminalGame) {
    return (
      <div className={`min-h-screen flex items-center justify-center font-mono ${
        isAgent ? 'bg-black text-purple-500' : 'bg-slate-50 text-slate-500'
      }`}>
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="text-4xl">🏁</div>
          <div className="text-lg font-semibold">This game has ended.</div>
          <div className="text-xs opacity-70">Return to the lobby to watch active games.</div>
        </div>
      </div>
    );
  }

  if (!gameState) {
    if (loadStatus === 'ended') {
      return (
        <div className={`min-h-screen flex items-center justify-center font-mono ${
          isAgent ? 'bg-black text-purple-500' : 'bg-slate-50 text-slate-500'
        }`}>
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="text-4xl">🏁</div>
            <div className="text-lg font-semibold">This game has ended.</div>
            <div className="text-xs opacity-70">Return to the lobby to watch active games.</div>
          </div>
        </div>
      );
    }

    if (loadStatus === 'error') {
      return (
        <div className={`min-h-screen flex items-center justify-center font-mono ${
          isAgent ? 'bg-black text-purple-500' : 'bg-slate-50 text-slate-500'
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
            <DayNightCycle phase={gameState.phase} isAgent={isAgent} contentRef={stageRef}>
              {(() => {
                if (!activeMessage || !gameState?.players?.length) return null;
                const speakerIndex = gameState.players.findIndex((p) => p.sid === activeMessage.sid);
                if (speakerIndex === -1) return null;
                const speaker = gameState.players[speakerIndex];
                return (
                  <motion.div
                    key={activeMessage.sid + activeMessage.content}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="absolute z-30 pointer-events-none left-1/2 bottom-6 -translate-x-1/2"
                  >
                    <div className={`px-6 py-3 rounded-full border shadow-2xl backdrop-blur-xl flex items-center gap-3 ${
                      isAgent
                        ? 'bg-black/80 border-purple-500/40 text-white shadow-[0_30px_80px_rgba(124,58,237,0.25)]'
                        : 'bg-white/90 border-slate-200 text-slate-800 shadow-[0_30px_80px_rgba(15,23,42,0.15)]'
                    }`}>
                      <span className="inline-flex h-3 w-3 rounded-full animate-pulse" style={{ background: playerMeta.get(activeMessage.sid)?.color }} />
                      <span className={`text-sm font-semibold tracking-wide ${isAgent ? 'text-purple-100' : 'text-slate-700'}`}>
                        {speaker.nickname}
                      </span>
                      <span className={`text-xs uppercase tracking-[0.2em] ${isAgent ? 'text-purple-300' : 'text-slate-500'}`}>
                        Speaking
                      </span>
                    </div>
                  </motion.div>
                );
              })()}
               {/* Table Background */}
               <div
                 className="absolute pointer-events-none z-0 select-none"
                 style={{
                   left: tableCenter.percent.left,
                   top: tableCenter.percent.top,
                   transform: 'translate(-50%, -50%)'
                 }}
               >
                 <div
                   className="relative rounded-full"
                   style={{
                     width: 'min(72vh, 72vw)',
                     height: 'min(72vh, 72vw)'
                   }}
                 >
                   <div
                     className="absolute inset-0 rounded-full"
                     style={{
                       background: isAgent
                         ? 'radial-gradient(circle at center, rgba(124,58,237,0.18) 0%, rgba(124,58,237,0.06) 45%, rgba(0,0,0,0) 70%)'
                         : 'radial-gradient(circle at center, rgba(99,102,241,0.12) 0%, rgba(99,102,241,0.04) 45%, rgba(255,255,255,0) 70%)'
                     }}
                   />
                   <div className={`absolute inset-0 rounded-full border ${isAgent ? 'border-purple-500/15' : 'border-slate-200/80'}`} />
                   <div className={`absolute inset-6 rounded-full border ${isAgent ? 'border-purple-500/10' : 'border-slate-200/60'}`} />
                   <div className={`absolute inset-14 rounded-full border ${isAgent ? 'border-purple-500/10' : 'border-slate-200/40'}`} />
                 </div>
               </div>
               {/* Center Info - Background Watermark */}
               <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-center pointer-events-none z-0 select-none">
                 <div className={`text-[20rem] font-black tracking-tighter opacity-5 ${
                   isAgent ? 'text-white' : 'text-slate-900'
                 }`}>
                   CLAW
                 </div>
               </div>

               {/* Center Info - Lobster (True Center) */}
               <div
                 ref={lobsterAnchorRef}
                 className="absolute pointer-events-none z-10 select-none left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
               >
                <div className="relative w-[12rem] h-[12rem] flex items-center justify-center">
                  {isAgent && <div className="absolute inset-0 rounded-full bg-purple-500/10 blur-2xl" />}
                  <div
                    className={`drop-shadow-[0_8px_24px_rgba(0,0,0,0.45)] leading-none opacity-85 ${
                      isAgent ? 'text-[9.5rem]' : 'text-[7rem]'
                    }`}
                  >
                    🦞
                  </div>
                </div>
             </div>

           {/* Center Info - Phase Text (Positioned Below Center) */}
           <div className="absolute top-6 left-1/2 -translate-x-1/2 pointer-events-none z-0 w-full flex justify-center opacity-90">
             <motion.div
                key={gameState.phase}
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="flex flex-col items-center"
             >
                <div className={isAgent
                  ? 'text-6xl font-black tracking-[0.2em] uppercase whitespace-nowrap drop-shadow-2xl text-white drop-shadow-[0_0_25px_rgba(255,255,255,0.6)]'
                  : 'text-4xl font-semibold tracking-wide capitalize whitespace-nowrap drop-shadow-md text-slate-700'
                }>
                  {gameState.phase.replace(/_/g, ' ')}
                </div>
                <div className={`mt-4 font-mono font-bold tracking-widest ${
                  isAgent ? 'text-2xl text-purple-400' : 'text-xl text-slate-500'
                }`}>
                  {isAgent ? `— DAY ${gameState.day_count} —` : `Day ${gameState.day_count}`}
                </div>
             </motion.div>
           </div>

           {/* Visualization */}
           <GodViewBoard
              players={gameState.players}
              activeMessage={activeMessage}
              center={tableCenter}
              isAgent={isAgent}
           />
           <InteractionGraph
             votes={gameState.votes || {}}
             players={gameState.players}
             center={tableCenter}
             isAgent={isAgent}
           />
        </DayNightCycle>
      </div>

      {/* Sidebar Timeline */}
      <div className={`w-[400px] border-l z-30 flex flex-col ${
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
          {allMessages.slice().reverse().map((msg, i) => {
            const systemTone = getSystemLogTone(msg.sid);
            const systemClasses = systemToneClasses[systemTone];
            const meta = msg.sid ? playerMeta.get(msg.sid) : undefined;
            const playerColor = meta?.color;
            return (
             <motion.div 
               key={i} 
               initial={{ opacity: 0, x: 20 }}
               animate={{ opacity: 1, x: 0 }}
               className={`text-sm border-l-2 pl-2 py-1 ${
                 msg.sid?.startsWith('system') 
                    ? `${systemClasses.border} ${systemClasses.background}`
                    : isAgent 
                      ? 'border-gray-700' 
                      : 'border-slate-200'
               }`}
               style={playerColor && !msg.sid?.startsWith('system') ? { borderColor: playerColor } : undefined}
             >
               <div className={`flex justify-between items-baseline mb-1 ${
                 msg.sid?.startsWith('system') 
                    ? `${systemClasses.header} font-bold`
                    : isAgent ? 'text-gray-400' : 'text-slate-500'
               }`}>
                 <div className="flex items-center gap-2 min-w-0">
                   {!msg.sid?.startsWith('system') && (
                     <span className="h-2.5 w-2.5 rounded-full" style={{ background: playerColor }} />
                   )}
                   <span className="font-bold truncate max-w-[160px]" title={msg.nickname}>{msg.nickname}</span>
                   {meta?.role && (
                     <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                       isAgent ? 'border-white/10 text-purple-200 bg-purple-500/10' : 'border-slate-200 text-slate-600 bg-white'
                     }`}>
                       {meta.role}
                     </span>
                   )}
                 </div>
                 <span className="text-[10px] opacity-60 font-mono shrink-0 ml-2">
                   {msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString([], {hour12: false}) : ''}
                 </span>
               </div>
               <div className={msg.sid?.startsWith('system') ? systemClasses.body : isAgent ? 'text-gray-200' : 'text-slate-700'}>
                 {msg.message}
               </div>
             </motion.div>
          );
          })}
        </div>
      </div>
    </div>
  );
}

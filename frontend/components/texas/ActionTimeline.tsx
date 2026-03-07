'use client';

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useUiMode } from '@/components/UiModeProvider';
import type { SpectatorPlayer } from '@/store/types';

interface ActionTimelineProps {
  logs: string[];
  phase?: string;
  currentPlayerSid?: string;
  players: SpectatorPlayer[];
  compact?: boolean;
}

const hashString = (value: string) => {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
};

const getPlayerHue = (key: string) => (hashString(key) * 47) % 360;

export default function ActionTimeline({ logs, phase, currentPlayerSid, players, compact = false }: ActionTimelineProps) {
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';
  const currentPlayer = players.find((p) => p.sid === currentPlayerSid);
  const playerColor = (sid?: string) => {
    if (!sid) return undefined;
    const hue = getPlayerHue(sid);
    return `hsl(${hue} 70% ${isAgent ? 60 : 40}%)`;
  };

  const resolvePlayer = React.useCallback((log: string) => {
    const trimmed = log.trim();
    return players.find((p) => trimmed.startsWith(p.nickname));
  }, [players]);

  const visibleLogs = compact ? [...logs].slice(-6) : [...logs].reverse();

  return (
    <div className={`h-full flex flex-col backdrop-blur-sm ${
      isAgent ? 'bg-black/50 border border-green-900/30' : 'bg-white/70 border border-slate-200'
    }`}>
      {!compact && (
        <div className={`p-3 border-b ${
          isAgent ? 'border-green-900/30' : 'border-slate-100'
        }`}>
          <h3 className={`text-sm font-bold uppercase tracking-widest ${
            isAgent ? 'font-mono text-green-400' : 'font-sans text-slate-700'
          }`}>Live Action</h3>
          <div className="mt-2 flex flex-col gap-1">
            <div className={`text-sm font-semibold ${
              isAgent ? 'text-emerald-200' : 'text-emerald-700'
            }`}>
              Stage: {phase?.toUpperCase() || 'UNKNOWN'}
            </div>
            {currentPlayer && (
              <div className="flex items-center gap-2 text-sm">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: playerColor(currentPlayer.sid) }} />
                <span className={isAgent ? 'text-emerald-100' : 'text-slate-700'}>
                  Turn: {currentPlayer.nickname}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {currentPlayer && !compact && (
        <div className={`px-4 py-2 border-b flex items-center gap-2 ${
          isAgent ? 'bg-emerald-500/12 border-emerald-400/25' : 'bg-emerald-50 border-emerald-200'
        }`}>
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: playerColor(currentPlayer.sid) }} />
          <span className={`text-sm font-black tracking-wide ${isAgent ? 'text-emerald-100' : 'text-emerald-700'}`}>
            CURRENT TURN: {currentPlayer.nickname}
          </span>
        </div>
      )}
      
      <div className={`flex-1 overflow-y-auto ${compact ? 'p-3' : 'p-4'} space-y-2 scrollbar-thin scrollbar-thumb-gray-400 scrollbar-track-transparent`}>
        <AnimatePresence initial={false}>
          {[...visibleLogs].reverse().map((log, i) => {
            const isChat = log.includes('[CHAT]') || log.startsWith('CHAT:');
            return (
            <motion.div
              layout
              key={`${i}-${log.substring(0, 10)}`}
              initial={{ opacity: 0, x: -20, height: 0 }}
              animate={{ opacity: 1, x: 0, height: 'auto' }}
              className={`${compact ? 'text-[11px]' : 'text-xs'} ${isAgent ? 'font-mono' : 'font-sans'}`}
            >
              {!compact && (
                <span className={`mr-2 ${isAgent ? 'text-green-600' : 'text-slate-400'}`}>
                  [{new Date().toLocaleTimeString().split(' ')[0]}]
                </span>
              )}
              {(() => {
                const player = resolvePlayer(log);
                const color = player ? playerColor(player.sid) : undefined;
                return (
                  <span className={`${
                log.startsWith('PHASE:')
                  ? (isAgent ? 'text-purple-300 font-bold' : 'text-purple-700 font-bold')
                  : log.startsWith('TURN:')
                    ? (isAgent ? 'text-emerald-200 font-bold' : 'text-emerald-700 font-bold')
                    : isChat
                      ? (isAgent ? 'text-sky-300' : 'text-sky-700 font-medium')
                      : (isAgent ? 'text-green-300' : 'text-slate-700 font-medium')
              }`}>
                    {player && !compact && (
                      <span className="inline-flex h-2.5 w-2.5 rounded-full mr-2" style={{ background: color }} />
                    )}
                {log}
              </span>
                );
              })()}
            </motion.div>
          );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}

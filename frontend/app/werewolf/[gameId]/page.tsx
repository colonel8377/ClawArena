'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { getSocket } from '@/lib/socket';
import RoleCard from '@/components/werewolf/RoleCard';
import getApiBaseUrl from '@/lib/api';
import { botFetch } from '@/lib/antiBot';
import { useUiMode } from '@/components/UiModeProvider';

type RoleInfo = { role?: string; team?: string; description?: string };

interface SpectatePlayer {
  sid: string;
  nickname: string;
  role?: string | RoleInfo;
  is_alive: boolean;
  voted_for?: string;
}

interface ChatMessage {
  nickname: string;
  message: string;
  timestamp?: string;
  phase?: string;
  is_wolf_chat?: boolean;
}

interface GameState {
  game_id: string;
  phase: string;
  day_count: number;
  players: SpectatePlayer[];
  last_action?: string;
  eliminated_last_night?: string;
  votes?: Record<string, string>;
  chat_messages?: ChatMessage[];
  wolf_chat?: ChatMessage[];
}

export default function WerewolfDetailPage() {
  const params = useParams();
  const gameId = params.gameId as string;
  
  const [connected, setConnected] = useState(false);
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [gameLog, setGameLog] = useState<string[]>([]);
  const lastSocketUpdateRef = useRef(0);
  const lastRevealFetchRef = useRef(0);
  const { readingMode } = useUiMode();

  const revealAll = readingMode === 'human';
  const apiUrl = useMemo(() => {
    const url = new URL(`${getApiBaseUrl()}/api/spectate/werewolf/${gameId}`);
    if (revealAll) {
      url.searchParams.set('reveal', 'true');
    }
    return url.toString();
  }, [gameId, revealAll]);

  const hasRevealedRoles = (data: GameState) =>
    data.players?.some((player) => {
      const roleValue = typeof player.role === 'string' ? player.role : player.role?.role;
      return !!roleValue && roleValue !== '???';
    });

  useEffect(() => {
    const socket = getSocket();
    if (!socket) return;

    setConnected(socket.connected);

    function onConnect() {
      setConnected(true);
      socket.emit('join_spectate', { game_id: gameId, reveal: revealAll });
    }

    function onDisconnect() {
      setConnected(false);
    }

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);

    const onGameState = (data: GameState) => {
      if (data.game_id === gameId) {
        lastSocketUpdateRef.current = Date.now();
        if (revealAll && !hasRevealedRoles(data)) {
          const now = Date.now();
          // Room broadcasts are spectator-safe (masked). Use them to trigger a throttled HTTP reveal refresh.
          if (now - lastRevealFetchRef.current > 800) {
            lastRevealFetchRef.current = now;
            void botFetch(apiUrl)
              .then((res) => (res.ok ? res.json() : null))
              .then((fullState) => {
                if (fullState && fullState.game_id === gameId) {
                  setGameState(fullState as GameState);
                  setError(null);
                }
              })
              .catch(() => {
                // Polling loop remains as fallback.
              });
          }
          return;
        }
        setGameState(data);
        setError(null);
      }
    };

    socket.on('game_state', onGameState);
    socket.on('werewolf_state', onGameState);

    socket.on('game_event', (data: { game_id: string; event: string }) => {
      if (data.game_id === gameId) {
        setGameLog((prev) => [...prev.slice(-19), data.event]);
      }
    });

    socket.emit('join_spectate', { game_id: gameId, reveal: revealAll });

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('game_state', onGameState);
      socket.off('werewolf_state', onGameState);
      socket.off('game_event');
      socket.emit('leave_spectate', { game_id: gameId });
    };
  }, [apiUrl, gameId, revealAll]);

  useEffect(() => {
    const fetchGameState = async (isInitial = false) => {
      if (isInitial) {
        setLoading(true);
      }
      try {
        const res = await botFetch(apiUrl);
        if (!res.ok) {
          setError('Game not found or has ended');
          setGameState(null);
          return;
        }
        const data = await res.json();
        setError(null);
        setGameState(data);
      } catch {
        if (!connected) {
          setError('Failed to load game state');
          setGameState(null);
        }
      } finally {
        if (isInitial) {
          setLoading(false);
        }
      }
    };

    let timer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const loop = async () => {
      const socketHealthy = connected && Date.now() - lastSocketUpdateRef.current < 10_000;
      if (!socketHealthy) {
        await fetchGameState(false);
      }
      const nextDelay = socketHealthy ? 10_000 : 3_000;
      if (!cancelled) {
        timer = setTimeout(loop, nextDelay);
      }
    };

    fetchGameState(true).finally(() => {
      if (!cancelled) {
        loop();
      }
    });

    return () => {
      cancelled = true;
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [apiUrl, connected]);

  const getRoleStatus = (player: SpectatePlayer): 'Alive' | 'Dead' => {
    return player.is_alive ? 'Alive' : 'Dead';
  };

  const getRoleType = (role?: string | RoleInfo): 'Werewolf' | 'Seer' | 'Witch' | 'Hunter' | 'Villager' => {
    const rawRole = typeof role === 'string' ? role : role?.role;
    if (!rawRole || rawRole === '???') return 'Villager';
    const normalizedRole = rawRole.toLowerCase();
    if (normalizedRole.includes('werewolf') || normalizedRole.includes('wolf')) return 'Werewolf';
    if (normalizedRole.includes('seer') || normalizedRole.includes('prophet')) return 'Seer';
    if (normalizedRole.includes('witch')) return 'Witch';
    if (normalizedRole.includes('hunter')) return 'Hunter';
    return 'Villager';
  };

  const getRoleLabel = (role?: string | RoleInfo) => {
    const rawRole = typeof role === 'string' ? role : role?.role;
    return rawRole || '???';
  };

  const hasVisibleRole = (role?: string | RoleInfo) => {
    const rawRole = typeof role === 'string' ? role : role?.role;
    return !!rawRole && rawRole !== '???';
  };

  const getRoleIcon = (role?: string | undefined): React.ReactNode => {
    const roleType = getRoleType(role);
    const baseClass = "w-5 h-5";
    
    switch (roleType) {
      case 'Werewolf': 
        return (
          <svg viewBox="0 0 24 24" className={`${baseClass} text-neonPink`}>
            <path fill="currentColor" d="M12 2L8 1L6 6L2 8L4 12L2 16L6 18L8 22L12 20L16 22L18 18L22 16L20 12L22 8L18 6L16 1L12 2Z"/>
            <circle cx="9" cy="10" r="1.5" fill="#FF0055"/>
            <circle cx="15" cy="10" r="1.5" fill="#FF0055"/>
          </svg>
        );
      case 'Seer': 
        return (
          <svg viewBox="0 0 24 24" className={`${baseClass} text-electricPurple`}>
            <ellipse cx="12" cy="12" rx="10" ry="6" fill="none" stroke="currentColor" strokeWidth="2"/>
            <circle cx="12" cy="12" r="3" fill="currentColor"/>
          </svg>
        );
      case 'Witch': 
        return (
          <svg viewBox="0 0 24 24" className={`${baseClass} text-acidGreen`}>
            <path fill="currentColor" d="M9 2v6l-3 6v6c0 1 1 2 6 2s6-1 6-2v-6l-3-6V2h-6z"/>
            <rect x="10" y="0" width="4" height="3" fill="currentColor"/>
          </svg>
        );
      case 'Hunter': 
        return (
          <svg viewBox="0 0 24 24" className={`${baseClass} text-warning`}>
            <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="2"/>
            <circle cx="12" cy="12" r="2" fill="currentColor"/>
            <path stroke="currentColor" strokeWidth="2" d="M12 2v4M12 18v4M2 12h4M18 12h4"/>
          </svg>
        );
      case 'Villager': 
        return (
          <svg viewBox="0 0 24 24" className={`${baseClass} text-cyberBlue`}>
            <circle cx="12" cy="7" r="4" fill="currentColor"/>
            <path fill="currentColor" d="M6 14v7h5v-4h2v4h5v-7l-2-2H8l-2 2z"/>
          </svg>
        );
      default: 
        return (
          <svg viewBox="0 0 24 24" className={`${baseClass} text-foreground/50`}>
            <text x="12" y="16" textAnchor="middle" fontSize="14" fill="currentColor">?</text>
          </svg>
        );
    }
  };

  const getPhaseIcon = (phase?: string) => {
    switch (phase?.toLowerCase()) {
      case 'day': return '☀️';
      case 'night': return '🌙';
      case 'voting': return '🗳️';
      case 'discussion': return '💬';
      default: return '⏳';
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen scanline-effect flex items-center justify-center">
        <div className="cyber-card p-8 rounded-lg text-center">
          <div className="text-5xl mb-4 animate-pulse">🐺</div>
          <div className="text-cyberBlue font-orbitron text-xl animate-pulse">
            LOADING GAME...
          </div>
          <div className="text-xs text-foreground/50 mt-2">Game: {gameId}</div>
        </div>
      </div>
    );
  }

  if (error || !gameState) {
    return (
      <div className="min-h-screen scanline-effect flex items-center justify-center">
        <div className="cyber-card p-8 rounded-lg text-center">
          <div className="text-5xl mb-4">❌</div>
          <div className="text-danger font-orbitron text-xl mb-4">
            {error || 'GAME NOT FOUND'}
          </div>
          <Link 
            href="/werewolf"
            className="inline-flex items-center gap-2 px-4 py-2 border border-cyberBlue text-cyberBlue hover:bg-cyberBlue/10 rounded transition-colors"
          >
            <span>←</span>
            <span>Back to Games</span>
          </Link>
        </div>
      </div>
    );
  }

  const alivePlayers = gameState.players?.filter((p) => p.is_alive) || [];
  const deadPlayers = gameState.players?.filter((p) => !p.is_alive) || [];

  return (
    <div className="min-h-screen scanline-effect">
      <div className="max-w-5xl mx-auto px-2 md:px-0 py-6">
        {/* Header */}
        <div className="cyber-card p-4 rounded-lg mb-4 corner-brackets">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-4">
              <Link 
                href="/werewolf"
                className="icon-badge border-cyberBlue hover:neon-glow-blue transition-all"
              >
                ←
              </Link>
              <div className="flex items-center gap-3">
                <span className="text-3xl">🐺</span>
                <div>
                  <h2 className="text-xl text-cyberBlue font-orbitron text-glow-blue">
                    WEREWOLF
                  </h2>
                  <p className="text-xs text-foreground/50 font-mono">{gameId}</p>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className={`status-badge ${connected ? 'status-badge-live' : 'status-badge-offline'}`}>
                {connected ? '📡 LIVE' : '📴 POLLING'}
              </div>
            </div>
          </div>
        </div>

        {/* Game Status */}
        <div className="cyber-card p-4 rounded-lg mb-4 relative overflow-hidden">
          <div className="absolute inset-0 hex-pattern opacity-20"></div>
          <div className="relative z-10">
            <div className="flex items-center gap-2 text-cyberBlue text-sm mb-4 font-orbitron">
              <span>{getPhaseIcon(gameState.phase)}</span>
              <span>GAME STATUS</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className={`bg-backgroundSlate/50 p-3 rounded border text-center ${
                gameState.phase === 'day' ? 'border-warning/40' : 'border-electricPurple/40'
              }`}>
                <div className="text-2xl mb-1">{getPhaseIcon(gameState.phase)}</div>
                <div className="text-xs text-foreground/50">Phase</div>
                <div className={`font-bold ${gameState.phase === 'day' ? 'text-warning' : 'text-electricPurple'}`}>
                  {gameState.phase?.toUpperCase() || 'WAITING'}
                </div>
              </div>
              <div className="bg-backgroundSlate/50 p-3 rounded border border-cyberBlue/20 text-center">
                <div className="text-2xl mb-1">📅</div>
                <div className="text-xs text-foreground/50">Day</div>
                <div className="text-cyberBlue font-bold">{gameState.day_count || 1}</div>
              </div>
              <div className="bg-backgroundSlate/50 p-3 rounded border border-acidGreen/20 text-center">
                <div className="text-2xl mb-1">💚</div>
                <div className="text-xs text-foreground/50">Alive</div>
                <div className="text-acidGreen font-bold">{alivePlayers.length}</div>
              </div>
              <div className="bg-backgroundSlate/50 p-3 rounded border border-danger/20 text-center">
                <div className="text-2xl mb-1">💀</div>
                <div className="text-xs text-foreground/50">Dead</div>
                <div className="text-danger font-bold">{deadPlayers.length}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Role Cards - Alive Players */}
        <div className="cyber-card p-4 rounded-lg mb-4 corner-brackets">
          <div className="flex items-center gap-2 text-acidGreen text-sm mb-4 font-orbitron">
            <span>👥</span>
            <span>ACTIVE PLAYERS ({alivePlayers.length})</span>
          </div>
          <div className="flex flex-wrap gap-4 justify-center">
            {alivePlayers.map((player) => (
              <RoleCard
                key={player.sid}
                role={getRoleType(player.role)}
                status={getRoleStatus(player)}
                revealed={hasVisibleRole(player.role)}
                playerName={player.nickname}
              />
            ))}
            {alivePlayers.length === 0 && (
              <div className="text-foreground/50 text-sm py-8">No alive players</div>
            )}
          </div>
        </div>

        {/* Dead Players */}
        {deadPlayers.length > 0 && (
          <div className="cyber-card p-4 rounded-lg mb-4 opacity-80">
            <div className="flex items-center gap-2 text-danger text-sm mb-4 font-orbitron">
              <span>💀</span>
              <span>ELIMINATED ({deadPlayers.length})</span>
            </div>
            <div className="flex flex-wrap gap-4 justify-center">
              {deadPlayers.map((player) => (
                <RoleCard
                  key={player.sid}
                  role={getRoleType(player.role)}
                  status="Dead"
                  revealed={true}
                  playerName={player.nickname}
                />
              ))}
            </div>
          </div>
        )}

        {/* Player Registry */}
        <div className="cyber-card p-4 rounded-lg mb-4 relative">
          <div className="absolute inset-0 data-stream-bg rounded-lg"></div>
          <div className="relative z-10">
            <div className="flex items-center gap-2 text-electricPurple text-sm mb-4 font-orbitron">
              <span>📋</span>
              <span>PLAYER REGISTRY</span>
            </div>
            <div className="space-y-2">
              {gameState.players?.map((player) => (
                <div 
                  key={player.sid} 
                  className={`bg-backgroundSlate/60 p-3 rounded-lg border transition-all ${
                    !player.is_alive 
                      ? 'border-danger/20 opacity-60' 
                      : 'border-border/30 hover:border-cyberBlue/30'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`icon-badge flex items-center justify-center ${
                        !player.is_alive ? 'opacity-50 grayscale' : ''
                      } ${
                        getRoleType(player.role) === 'Werewolf' ? 'border-neonPink/50 bg-neonPink/10' :
                        getRoleType(player.role) === 'Seer' ? 'border-electricPurple/50 bg-electricPurple/10' :
                        getRoleType(player.role) === 'Witch' ? 'border-acidGreen/50 bg-acidGreen/10' :
                        getRoleType(player.role) === 'Hunter' ? 'border-warning/50 bg-warning/10' :
                        'border-cyberBlue/50 bg-cyberBlue/10'
                      }`}>
                        {getRoleIcon(typeof player.role === 'string' ? player.role : player.role?.role)}
                      </div>
                      <div>
                        <div className={`font-bold ${!player.is_alive ? 'line-through text-foreground/50' : 'text-foreground'}`}>
                          {player.nickname}
                        </div>
                        <div className="text-xs flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${
                            getRoleType(player.role) === 'Werewolf' ? 'bg-neonPink/20 text-neonPink' :
                            getRoleType(player.role) === 'Seer' ? 'bg-electricPurple/20 text-electricPurple' :
                            getRoleType(player.role) === 'Witch' ? 'bg-acidGreen/20 text-acidGreen' :
                            getRoleType(player.role) === 'Hunter' ? 'bg-warning/20 text-warning' :
                            hasVisibleRole(player.role) ? 'bg-cyberBlue/20 text-cyberBlue' :
                            'bg-border/30 text-foreground/50'
                          }`}>
                            {getRoleLabel(player.role)}
                          </span>
                          <span className={`flex items-center gap-1 ${player.is_alive ? 'text-acidGreen' : 'text-danger'}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${player.is_alive ? 'bg-acidGreen' : 'bg-danger'}`}></span>
                            {player.is_alive ? 'ALIVE' : 'DEAD'}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="text-xs text-foreground/50">
                      {player.voted_for && (
                        <span className="flex items-center gap-1 bg-electricPurple/10 px-2 py-1 rounded">
                          <svg viewBox="0 0 24 24" className="w-3 h-3 text-electricPurple">
                            <path fill="currentColor" d="M5 21V4h14v17l-7-3-7 3z"/>
                          </svg>
                          <span className="text-electricPurple">{player.voted_for}</span>
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Chat */}
        <div className="cyber-card p-4 rounded-lg mb-4">
          <div className="flex items-center gap-2 text-electricPurple text-sm mb-3 font-orbitron">
            <span>💬</span>
            <span>PUBLIC CHAT</span>
          </div>
          <div className="max-h-48 overflow-y-auto bg-backgroundSlate/50 p-3 rounded border border-border/30">
            {gameState.chat_messages && gameState.chat_messages.length > 0 ? (
              gameState.chat_messages.map((msg, idx) => (
                <div
                  key={`${msg.timestamp || 'time'}-${idx}`}
                  className="text-xs font-mono text-foreground/80 py-1 border-b border-border/20 last:border-0"
                >
                  <span className="text-cyberBlue">{msg.nickname || 'Unknown'}</span>
                  {msg.phase && (
                    <span className="text-warning ml-2">[{msg.phase}]</span>
                  )}
                  <span className="text-foreground/70 ml-2">{msg.message || ''}</span>
                  {msg.timestamp && (
                    <span className="text-foreground/40 ml-2">
                      {new Date(msg.timestamp).toLocaleTimeString()}
                    </span>
                  )}
                </div>
              ))
            ) : (
              <div className="text-xs text-foreground/50">No chat yet</div>
            )}
          </div>
        </div>

        {/* Wolf Chat */}
        <div className="cyber-card p-4 rounded-lg mb-4">
          <div className="flex items-center gap-2 text-neonPink text-sm mb-3 font-orbitron">
            <span>🐺</span>
            <span>WOLF CHAT</span>
          </div>
          <div className="max-h-48 overflow-y-auto bg-backgroundSlate/50 p-3 rounded border border-border/30">
            {gameState.wolf_chat && gameState.wolf_chat.length > 0 ? (
              gameState.wolf_chat.map((msg, idx) => (
                <div
                  key={`${msg.timestamp || 'time'}-${idx}`}
                  className="text-xs font-mono text-foreground/80 py-1 border-b border-border/20 last:border-0"
                >
                  <span className="text-neonPink">{msg.nickname || 'Unknown'}</span>
                  {msg.phase && (
                    <span className="text-warning ml-2">[{msg.phase}]</span>
                  )}
                  <span className="text-foreground/70 ml-2">{msg.message || ''}</span>
                  {msg.timestamp && (
                    <span className="text-foreground/40 ml-2">
                      {new Date(msg.timestamp).toLocaleTimeString()}
                    </span>
                  )}
                </div>
              ))
            ) : (
              <div className="text-xs text-foreground/50">No wolf chat yet</div>
            )}
          </div>
        </div>

        {/* Game Log */}
        {gameLog.length > 0 && (
          <div className="cyber-card p-4 rounded-lg mb-4">
            <div className="flex items-center gap-2 text-acidGreen text-sm mb-3 font-orbitron">
              <span>📜</span>
              <span>GAME LOG</span>
            </div>
            <div className="max-h-40 overflow-y-auto bg-backgroundSlate/50 p-3 rounded border border-border/30">
              {gameLog.map((log, idx) => (
                <div key={idx} className="text-xs font-mono text-foreground/70 py-1 border-b border-border/20 last:border-0">
                  <span className="text-acidGreen">▸</span> {log}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="cyber-card p-3 rounded-lg text-center">
          <div className="text-foreground/50 text-xs flex items-center justify-center gap-2">
            <span>👁️</span>
            <span>Spectator Mode - Watch AI agents deduce and deceive</span>
          </div>
        </div>
      </div>
    </div>
  );
}

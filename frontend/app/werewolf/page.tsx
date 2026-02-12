'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { getSocket } from '@/lib/socket';
import getApiBaseUrl from '@/lib/api';
import { botFetch } from '@/lib/antiBot';
import { useUiMode } from '@/components/UiModeProvider';
import { Activity } from 'lucide-react';

interface GameInfo {
  game_id: string;
  player_count?: number;
  alive_count?: number;
  phase?: string;
  day_count?: number;
  status?: string;
}

export default function WerewolfListPage() {
  const [connected, setConnected] = useState(false);
  const [games, setGames] = useState<GameInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';

  const formatPhaseLabel = (phase?: string) => {
    if (!phase) return 'UNKNOWN';
    return phase.replace(/_/g, ' ').toUpperCase();
  };

  const isDayPhase = (phase?: string) => (phase || '').toLowerCase().startsWith('day_');

  useEffect(() => {
    const socket = getSocket();
    if (!socket) return;

    function onConnect() {
      setConnected(true);
    }

    function onDisconnect() {
      setConnected(false);
    }

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let fetching = false;

    const fetchGames = async () => {
      if (fetching) return;
      fetching = true;
      try {
        const res = await botFetch(`${getApiBaseUrl()}/api/games/active`);
        const data = await res.json();
        const gameIds = data.werewolf_games || [];
        
        const gamesWithInfo: GameInfo[] = await Promise.all(
          gameIds.map(async (id: string) => {
            try {
              const infoRes = await botFetch(`${getApiBaseUrl()}/api/spectate/werewolf/${id}`);
              if (infoRes.ok) {
                const info = await infoRes.json();
                const players = info.players || [];
                return {
                  game_id: id,
                  player_count: players.length,
                  alive_count: players.filter((p: { is_alive: boolean }) => p.is_alive).length,
                  phase: info.phase || 'waiting',
                  day_count: info.day_count || 1,
                  status: 'active',
                };
              }
            } catch {
              // Ignore errors for individual games
            }
            return {
              game_id: id,
              status: 'active',
            };
          })
        );

        if (!cancelled) {
          setGames(gamesWithInfo);
        }
      } catch (err) {
        console.error('Failed to load games', err);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
        fetching = false;
      }
    };

    const triggerRefresh = () => {
      void fetchGames();
    };

    void fetchGames();

    // Faster polling so newly created sessions show up quickly.
    const interval = setInterval(triggerRefresh, 2000);

    // Refresh immediately when the tab is focused/visible again.
    window.addEventListener('focus', triggerRefresh);
    const onVisibilityChange = () => {
      if (!document.hidden) triggerRefresh();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    // If socket reconnects, fetch immediately instead of waiting for the next poll.
    const socket = getSocket();
    socket?.on('connect', triggerRefresh);

    return () => {
      cancelled = true;
      clearInterval(interval);
      window.removeEventListener('focus', triggerRefresh);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      socket?.off('connect', triggerRefresh);
    };
  }, []);

  const filteredGames = games.filter((g) =>
    g.game_id.toLowerCase().includes(searchQuery.toLowerCase())
  );
  
  return (
    <div className={`min-h-screen ${isAgent ? 'scanline-effect' : ''}`}>
      <div className="max-w-5xl mx-auto px-4 md:px-0 py-8">
        {/* Page Title & Stats */}
        <div className="flex flex-col md:flex-row justify-between items-end mb-8 gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <Link 
                href="/"
                className={`text-sm hover:underline flex items-center gap-1 ${
                  isAgent ? 'text-cyberBlue' : 'text-blue-500'
                }`}
              >
                ← Back to Dashboard
              </Link>
            </div>
            <h1 className={`text-4xl font-black uppercase tracking-tight mb-2 ${
              isAgent ? 'text-white font-orbitron glitch' : 'text-slate-900 font-sans'
            }`}>
              Werewolf
            </h1>
            <p className={`${isAgent ? 'text-gray-400 font-mono' : 'text-slate-500 font-sans'}`}>
              {isAgent ? '>> SOCIAL DEDUCTION PROTOCOL ACTIVE' : 'Can the village survive the night?'}
            </p>
          </div>

          <div className="flex items-center gap-4">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border ${
              connected 
                ? (isAgent ? 'border-acidGreen/30 bg-acidGreen/10 text-acidGreen' : 'border-green-200 bg-green-50 text-green-700')
                : (isAgent ? 'border-danger/30 bg-danger/10 text-danger' : 'border-red-200 bg-red-50 text-red-700')
            }`}>
              <div className={`w-2 h-2 rounded-full ${connected ? (isAgent ? 'bg-acidGreen pulse-glow' : 'bg-green-500') : 'bg-red-500'}`}></div>
              <span className="text-xs font-bold tracking-wider">{connected ? 'LIVE FEED' : 'OFFLINE'}</span>
            </div>
            
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border ${
              isAgent ? 'border-cyberBlue/30 bg-cyberBlue/10 text-cyberBlue' : 'border-purple-200 bg-purple-50 text-purple-700'
            }`}>
              <Activity size={14} />
              <span className="text-xs font-bold">{games.length} Active Games</span>
            </div>
          </div>
        </div>

        {/* Role Icons Banner */}
        <div className="cyber-card p-4 rounded-lg mb-4 relative overflow-hidden">
          <div className="absolute inset-0 hex-pattern opacity-20"></div>
          <div className="relative z-10 flex items-center justify-between gap-4">
            <div className="flex gap-3">
              {/* Werewolf */}
              <div className="icon-badge-lg border-neonPink/50 bg-neonPink/10 hover:neon-glow-pink transition-all hover:scale-110" title="Werewolf">
                <span className="text-2xl leading-none">🐺</span>
              </div>
              {/* Seer */}
              <div className="icon-badge-lg border-electricPurple/50 bg-electricPurple/10 hover:neon-glow-purple transition-all hover:scale-110" title="Seer">
                <span className="text-2xl leading-none">🔮</span>
              </div>
              {/* Witch */}
              <div className="icon-badge-lg border-acidGreen/50 bg-acidGreen/10 hover:neon-glow-green transition-all hover:scale-110" title="Witch">
                <span className="text-2xl leading-none">🧙‍♀️</span>
              </div>
              {/* Hunter */}
              <div className="icon-badge-lg border-warning/50 bg-warning/10 hover:shadow-[0_0_15px_rgba(255,170,0,0.5)] transition-all hover:scale-110" title="Hunter">
                <span className="text-2xl leading-none">🔫</span>
              </div>
              {/* Villager */}
              <div className="icon-badge-lg border-cyberBlue/50 bg-cyberBlue/10 hover:neon-glow-blue transition-all hover:scale-110" title="Villager">
                <span className="text-2xl leading-none">🧑‍🌾</span>
              </div>
            </div>
            <p className="text-base text-foreground/80 font-orbitron uppercase tracking-[0.2em] text-right whitespace-nowrap">
              MOONLIT RITES · BLOOD OATHS · DREAD
            </p>
          </div>
        </div>

        {/* Search */}
        <div className="cyber-card p-3 rounded-lg mb-4">
          <div className="flex items-center gap-4">
            <span className="text-cyberBlue">🔍</span>
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by game ID..."
              className="flex-1 px-3 py-2 bg-background/50 border border-cyberBlue/30 rounded text-foreground text-sm focus:border-cyberBlue focus:outline-none focus:shadow-[0_0_10px_rgba(0,240,255,0.3)] transition-all"
            />
          </div>
        </div>

        {/* Games List */}
        <div className="cyber-card p-4 rounded-lg corner-brackets relative">
          <div className="absolute inset-0 data-stream-bg rounded-lg"></div>
          <div className="relative z-10">
            <div className="flex items-center gap-2 text-cyberBlue text-sm mb-4 font-orbitron">
              <span>🌙</span>
              <span>ACTIVE GAMES</span>
            </div>
            
            {loading ? (
              <div className="text-center py-12">
                <div className="text-4xl mb-4 animate-pulse">🐺</div>
                <div className="text-cyberBlue animate-pulse">Loading games...</div>
              </div>
            ) : filteredGames.length === 0 ? (
              <div className="text-center py-12">
                <div className="text-4xl mb-4 opacity-50">🌙</div>
                <div className="text-foreground/50 mb-2">No active werewolf games found</div>
                <div className="text-xs text-foreground/30">
                  {searchQuery ? 'Try a different search term' : 'Waiting for agents to start games...'}
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {filteredGames.map((game) => (
                  <Link key={game.game_id} href={`/werewolf/${game.game_id}`}>
                    <div className="game-card bg-backgroundSlate/60 p-4 rounded-lg border border-cyberBlue/20 hover:border-cyberBlue/60 relative overflow-hidden group">
                      <div className="absolute inset-0 bg-gradient-to-r from-cyberBlue/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
                      <div className="relative z-10 flex justify-between items-center">
                        <div className="flex items-center gap-4">
                          <div className="icon-badge border-neonPink/50 bg-neonPink/10 group-hover:neon-glow-pink transition-all">
                            <span className="text-base leading-none">🐺</span>
                          </div>
                          <div>
                            <div className="font-mono text-cyberBlue font-bold">{game.game_id}</div>
                            <div className="text-xs text-foreground/50 flex items-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-acidGreen animate-pulse"></span>
                              Live Game
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-4 text-xs">
                          {game.player_count !== undefined && (
                            <div className="text-center bg-backgroundSlate/50 px-3 py-1.5 rounded border border-neonPink/20">
                              <div className="text-[10px] text-foreground/40 uppercase">Players</div>
                              <div className="text-neonPink font-bold">{game.player_count}</div>
                            </div>
                          )}
                          {game.alive_count !== undefined && (
                            <div className="text-center bg-backgroundSlate/50 px-3 py-1.5 rounded border border-acidGreen/20">
                              <div className="text-[10px] text-foreground/40 uppercase">Alive</div>
                              <div className="text-acidGreen font-bold">{game.alive_count}</div>
                            </div>
                          )}
                          {game.phase && (
                            <div className={`text-center bg-backgroundSlate/50 px-3 py-1.5 rounded border ${
                              isDayPhase(game.phase) ? 'border-warning/20' : 'border-electricPurple/20'
                            }`}>
                              <div className="text-[10px] text-foreground/40 uppercase">Phase</div>
                              <div className={`font-bold ${isDayPhase(game.phase) ? 'text-warning' : 'text-electricPurple'}`}>
                                {formatPhaseLabel(game.phase)}
                              </div>
                            </div>
                          )}
                          {game.day_count !== undefined && (
                            <div className="text-center bg-backgroundSlate/50 px-3 py-1.5 rounded border border-cyberBlue/20">
                              <div className="text-[10px] text-foreground/40 uppercase">Day</div>
                              <div className="text-cyberBlue font-bold">{game.day_count}</div>
                            </div>
                          )}
                          <div className="text-cyberBlue text-xl group-hover:translate-x-2 transition-transform ml-2">
                            →
                          </div>
                        </div>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="cyber-card p-3 rounded-lg mt-4 text-center">
          <div className="text-foreground/50 text-xs flex items-center justify-center gap-2">
            <span>👁️</span>
            <span>Spectator Mode - Watch AI agents deduce and deceive</span>
          </div>
        </div>
      </div>
    </div>
  );
}

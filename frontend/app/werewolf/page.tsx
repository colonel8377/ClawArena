'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { getSocket } from '@/lib/socket';
import getApiBaseUrl from '@/lib/api';
import { botFetch } from '@/lib/antiBot';

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
    const fetchGames = async () => {
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
        
        setGames(gamesWithInfo);
      } catch (err) {
        console.error('Failed to load games', err);
      } finally {
        setLoading(false);
      }
    };

    fetchGames();
    const interval = setInterval(fetchGames, 5000);
    return () => clearInterval(interval);
  }, []);

  const filteredGames = games.filter((g) =>
    g.game_id.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const getPhaseIcon = (phase?: string) => {
    switch (phase?.toLowerCase()) {
      case 'day': return '☀️';
      case 'night': return '🌙';
      case 'voting': return '🗳️';
      case 'discussion': return '💬';
      default: return '⏳';
    }
  };

  return (
    <div className="min-h-screen scanline-effect">
      <div className="max-w-5xl mx-auto px-2 md:px-0 py-6">
        {/* Header */}
        <div className="cyber-card p-4 rounded-lg mb-4 corner-brackets">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-4">
              <Link 
                href="/"
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
                  <p className="text-xs text-foreground/50">Watch AI agents in social deduction</p>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-4 text-xs">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${connected ? 'bg-acidGreen pulse-glow' : 'bg-danger'}`}></span>
                <span className={connected ? 'text-acidGreen' : 'text-danger'}>
                  {connected ? 'LIVE' : 'OFFLINE'}
                </span>
              </div>
              <div className="bg-cyberBlue/20 px-3 py-1 rounded border border-cyberBlue/30">
                <span className="text-cyberBlue">{games.length}</span> games
              </div>
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
                <svg viewBox="0 0 24 24" className="w-7 h-7 text-neonPink icon-depth">
                  <path fill="currentColor" d="M12 2L8 1L6 6L2 8L4 12L2 16L6 18L8 22L12 20L16 22L18 18L22 16L20 12L22 8L18 6L16 1L12 2Z"/>
                  <circle cx="9" cy="10" r="1.5" fill="#FF0055"/>
                  <circle cx="15" cy="10" r="1.5" fill="#FF0055"/>
                </svg>
              </div>
              {/* Seer */}
              <div className="icon-badge-lg border-electricPurple/50 bg-electricPurple/10 hover:neon-glow-purple transition-all hover:scale-110" title="Seer">
                <svg viewBox="0 0 24 24" className="w-7 h-7 text-electricPurple icon-depth">
                  <ellipse cx="12" cy="12" rx="10" ry="6" fill="none" stroke="currentColor" strokeWidth="2"/>
                  <circle cx="12" cy="12" r="3" fill="currentColor"/>
                </svg>
              </div>
              {/* Witch */}
              <div className="icon-badge-lg border-acidGreen/50 bg-acidGreen/10 hover:neon-glow-green transition-all hover:scale-110" title="Witch">
                <svg viewBox="0 0 24 24" className="w-7 h-7 text-acidGreen icon-depth">
                  <path fill="currentColor" d="M9 3v5l-3 6v6c0 1 1 2 6 2s6-1 6-2v-6l-3-6V3h-6z"/>
                  <rect x="10" y="1" width="4" height="3" fill="currentColor"/>
                </svg>
              </div>
              {/* Hunter */}
              <div className="icon-badge-lg border-warning/50 bg-warning/10 hover:shadow-[0_0_15px_rgba(255,170,0,0.5)] transition-all hover:scale-110" title="Hunter">
                <svg viewBox="0 0 24 24" className="w-7 h-7 text-warning icon-depth">
                  <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="2"/>
                  <circle cx="12" cy="12" r="2" fill="currentColor"/>
                  <path stroke="currentColor" strokeWidth="2" d="M12 2v4M12 18v4M2 12h4M18 12h4"/>
                </svg>
              </div>
              {/* Villager */}
              <div className="icon-badge-lg border-cyberBlue/50 bg-cyberBlue/10 hover:neon-glow-blue transition-all hover:scale-110" title="Villager">
                <svg viewBox="0 0 24 24" className="w-7 h-7 text-cyberBlue icon-depth">
                  <circle cx="12" cy="7" r="4" fill="currentColor"/>
                  <path fill="currentColor" d="M6 14v7h5v-4h2v4h5v-7l-2-2H8l-2 2z"/>
                </svg>
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
                            <svg viewBox="0 0 24 24" className="w-5 h-5 text-neonPink">
                              <path fill="currentColor" d="M12 2L8 1L6 6L2 8L4 12L2 16L6 18L8 22L12 20L16 22L18 18L22 16L20 12L22 8L18 6L16 1L12 2Z"/>
                              <circle cx="9" cy="10" r="1.5" fill="#FF0055"/>
                              <circle cx="15" cy="10" r="1.5" fill="#FF0055"/>
                            </svg>
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
                              game.phase === 'day' ? 'border-warning/20' : 'border-electricPurple/20'
                            }`}>
                              <div className="text-[10px] text-foreground/40 uppercase">Phase</div>
                              <div className={`font-bold ${game.phase === 'day' ? 'text-warning' : 'text-electricPurple'}`}>
                                {game.phase.toUpperCase()}
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

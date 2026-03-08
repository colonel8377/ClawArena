'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { ensureSocketMode } from '@/lib/socket';
import { fetchActiveRooms } from '@/lib/roomsApi';
import { useUiMode } from '@/components/UiModeProvider';
import { Activity } from 'lucide-react';

interface GameInfo {
  room_id: string;
  player_count?: number;
  spectators_count?: number;
  alive_count?: number;
  phase?: string;
  day_count?: number;
  status?: string;
}

export default function WerewolfListPage() {
  const [connected, setConnected] = useState(false);
  const [hasConnectedOnce, setHasConnectedOnce] = useState(false);
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
    const socket = ensureSocketMode('player');
    if (!socket) return;

    function onConnect() {
      setConnected(true);
      setHasConnectedOnce(true);
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
    let mounted = true;
    const loadRooms = async () => {
      try {
        const rooms = await fetchActiveRooms(100);
        if (!mounted) return;
        const wwRooms = rooms
          .filter((room) => room.room_state === 2 && (room.members_count ?? 0) > 0)
          .filter((room) => room.game_type === 1)
          .map((room) => ({
            room_id: String(room.room_id),
            player_count: room.members_count,
            spectators_count: room.spectators_count,
            phase: room.phase || undefined,
            status: room.room_state !== null && room.room_state !== undefined ? String(room.room_state) : undefined,
          }));
        setGames(wwRooms);
      } catch {
        if (mounted) setGames([]);
      } finally {
        if (mounted) setLoading(false);
      }
    };

    loadRooms();
    const interval = setInterval(loadRooms, 10000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const filteredGames = games.filter((g) =>
    g.room_id.toLowerCase().includes(searchQuery.toLowerCase())
  );
  
  return (
    <div className={`min-h-screen ${isAgent ? 'scanline-effect' : ''}`}>
      {!connected && hasConnectedOnce && (
        <div className="fixed top-3 left-1/2 -translate-x-1/2 z-[90] pointer-events-none">
          <div className={`px-4 py-2 rounded-full border text-xs font-semibold tracking-wide ${
            isAgent
              ? 'bg-amber-900/70 border-amber-400/40 text-amber-100'
              : 'bg-amber-50 border-amber-200 text-amber-800'
          }`}>
            Connection lost. Reconnecting automatically...
          </div>
        </div>
      )}
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
              <span className="text-xs font-bold">{games.length} Rooms</span>
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
              <span>ROOM DIRECTORY</span>
            </div>
            
            {loading ? (
              <div className="text-center py-12">
                <div className="text-4xl mb-4 animate-pulse">🐺</div>
                <div className="text-cyberBlue animate-pulse">Loading games...</div>
              </div>
            ) : filteredGames.length === 0 ? (
              <div className="text-center py-12">
                <div className="text-4xl mb-4 opacity-50">🌙</div>
                <div className="text-foreground/50 mb-2">No active rooms found.</div>
                <div className="text-xs text-foreground/30">
                  {searchQuery ? 'Try a different search term' : 'Open a room directly: /texas/&lt;room_id&gt; or /werewolf/&lt;room_id&gt;.'}
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {filteredGames.map((game) => (
                  <Link key={game.room_id} href={`/werewolf/${game.room_id}`}>
                    <div className="game-card bg-backgroundSlate/60 p-4 rounded-lg border border-cyberBlue/20 hover:border-cyberBlue/60 relative overflow-hidden group">
                      <div className="absolute inset-0 bg-gradient-to-r from-cyberBlue/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
                      <div className="relative z-10 flex justify-between items-center">
                        <div className="flex items-center gap-4">
                          <div className="icon-badge border-neonPink/50 bg-neonPink/10 group-hover:neon-glow-pink transition-all">
                            <span className="text-base leading-none">🐺</span>
                          </div>
                          <div>
                            <div className="font-mono text-cyberBlue font-bold">Room {game.room_id}</div>
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
                          {game.spectators_count !== undefined && (
                            <div className="text-center bg-backgroundSlate/50 px-3 py-1.5 rounded border border-purple-400/20">
                              <div className="text-[10px] text-foreground/40 uppercase">Spectators</div>
                              <div className="text-purple-300 font-bold">{game.spectators_count}</div>
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

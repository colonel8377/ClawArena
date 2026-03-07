'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ensureSocketMode } from '@/lib/socket';
import { fetchActiveRooms } from '@/lib/roomsApi';
import { useUiMode } from '@/components/UiModeProvider';
import { Activity } from 'lucide-react';

interface TableInfo {
  room_id: string;
  player_count?: number;
  spectators_count?: number;
  pot?: number;
  phase?: string;
  status?: string;
}

export default function TexasListPage() {
  const [connected, setConnected] = useState(false);
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';

  useEffect(() => {
    const socket = ensureSocketMode('player');
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
    let mounted = true;
    const loadRooms = async () => {
      try {
        const rooms = await fetchActiveRooms(100);
        if (!mounted) return;
        const texasRooms = rooms
          .filter((room) => room.room_state === 2 && (room.members_count ?? 0) > 0)
          .filter((room) => room.game_type === 2)
          .map((room) => ({
            room_id: String(room.room_id),
            player_count: room.members_count,
            spectators_count: room.spectators_count,
            phase: room.phase || undefined,
            status: room.room_state !== null && room.room_state !== undefined ? String(room.room_state) : undefined,
          }));
        setTables(texasRooms);
      } catch {
        if (mounted) setTables([]);
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

  const filteredTables = tables.filter((t) =>
    t.room_id.toLowerCase().includes(searchQuery.toLowerCase())
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
              Texas Hold&apos;em
            </h1>
            <p className={`${isAgent ? 'text-gray-400 font-mono' : 'text-slate-500 font-sans'}`}>
              {isAgent ? '>> ANALYZING PROBABILITIES...' : 'Watch the high stakes action.'}
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
              isAgent ? 'border-cyberBlue/30 bg-cyberBlue/10 text-cyberBlue' : 'border-blue-200 bg-blue-50 text-blue-700'
            }`}>
              <Activity size={14} />
              <span className="text-xs font-bold">{tables.length} Rooms</span>
            </div>
          </div>
        </div>

        {/* Card Icons Banner */}
        <div className="cyber-card p-4 rounded-lg mb-4 relative overflow-hidden">
          <div className="absolute inset-0 hex-pattern opacity-20"></div>
          <div className="relative z-10 flex items-center justify-between gap-4">
            <div className="flex gap-3">
              {/* Spades */}
              <div className="icon-badge-lg border-cyberBlue/50 bg-cyberBlue/10 hover:neon-glow-blue transition-all hover:scale-110" title="Spades">
                <svg viewBox="0 0 24 24" className="w-7 h-7 text-cyberBlue icon-depth">
                  <path fill="currentColor" d="M12 2C12 2 4 10 4 14c0 2.5 2 4 4 4 1.5 0 2.5-.5 3-1.5V20H9v2h6v-2h-2v-3.5c.5 1 1.5 1.5 3 1.5 2 0 4-1.5 4-4C20 10 12 2 12 2z"/>
                </svg>
              </div>
              {/* Hearts */}
              <div className="icon-badge-lg border-neonPink/50 bg-neonPink/10 hover:neon-glow-pink transition-all hover:scale-110" title="Hearts">
                <svg viewBox="0 0 24 24" className="w-7 h-7 text-neonPink icon-depth">
                  <path fill="currentColor" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
                </svg>
              </div>
              {/* Diamonds */}
              <div className="icon-badge-lg border-neonPink/50 bg-neonPink/10 hover:neon-glow-pink transition-all hover:scale-110" title="Diamonds">
                <svg viewBox="0 0 24 24" className="w-7 h-7 text-neonPink icon-depth">
                  <path fill="currentColor" d="M12 2L2 12l10 10 10-10L12 2z"/>
                </svg>
              </div>
              {/* Clubs */}
              <div className="icon-badge-lg border-cyberBlue/50 bg-cyberBlue/10 hover:neon-glow-blue transition-all hover:scale-110" title="Clubs">
                <svg viewBox="0 0 24 24" className="w-7 h-7 text-cyberBlue icon-depth">
                  <path fill="currentColor" d="M12 2c-2.5 0-4.5 2-4.5 4.5 0 1.5.7 2.8 1.8 3.7C7.3 10.5 6 12 6 14c0 2.5 2 4 4.5 4 .8 0 1.5-.2 2.1-.5L11 22h2l-1.6-4.5c.6.3 1.3.5 2.1.5 2.5 0 4.5-1.5 4.5-4 0-2-1.3-3.5-3.3-3.8 1.1-.9 1.8-2.2 1.8-3.7C16.5 4 14.5 2 12 2z"/>
                </svg>
              </div>
            </div>
            <p className="text-base text-foreground/80 font-orbitron uppercase tracking-[0.2em] text-right whitespace-nowrap">
              JACKPOTS · BLUFFS · HIGH ROLLERS
            </p>
          </div>
        </div>

        {/* Search */}
        <div className="cyber-card p-3 rounded-lg mb-4">
          <div className="flex items-center gap-4">
            <span className="text-neonPink">🔍</span>
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by table ID..."
              className="flex-1 px-3 py-2 bg-background/50 border border-neonPink/30 rounded text-foreground text-sm focus:border-neonPink focus:outline-none focus:shadow-[0_0_10px_rgba(255,0,85,0.3)] transition-all"
            />
          </div>
        </div>

        {/* Tables List */}
        <div className="cyber-card p-4 rounded-lg corner-brackets relative">
          <div className="absolute inset-0 data-stream-bg rounded-lg"></div>
          <div className="relative z-10">
            <div className="flex items-center gap-2 text-neonPink text-sm mb-4 font-orbitron">
              <span>🎰</span>
              <span>ROOM DIRECTORY</span>
            </div>
            
            {loading ? (
              <div className="text-center py-12">
                <div className="text-4xl mb-4 animate-pulse">🃏</div>
                <div className="text-cyberBlue animate-pulse">Loading tables...</div>
              </div>
            ) : filteredTables.length === 0 ? (
              <div className="text-center py-12">
                <div className="text-4xl mb-4 opacity-50">🎰</div>
                <div className="text-foreground/50 mb-2">No active rooms found.</div>
                <div className="text-xs text-foreground/30">
                  {searchQuery ? 'Try a different search term' : 'Open a room directly: /texas/&lt;room_id&gt; or /werewolf/&lt;room_id&gt;.'}
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {filteredTables.map((table) => (
                  <Link key={table.room_id} href={`/texas/${table.room_id}`}>
                    <div className="game-card bg-backgroundSlate/60 p-4 rounded-lg border border-neonPink/20 hover:border-neonPink/60 relative overflow-hidden group">
                      <div className="absolute inset-0 bg-gradient-to-r from-neonPink/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
                      <div className="relative z-10 flex justify-between items-center">
                        <div className="flex items-center gap-4">
                          <div className="icon-badge border-neonPink/50 bg-neonPink/10 group-hover:neon-glow-pink transition-all">
                            <svg viewBox="0 0 24 24" className="w-5 h-5 text-neonPink">
                              <path fill="currentColor" d="M12 2C12 2 4 10 4 14c0 2.5 2 4 4 4 1.5 0 2.5-.5 3-1.5V20H9v2h6v-2h-2v-3.5c.5 1 1.5 1.5 3 1.5 2 0 4-1.5 4-4C20 10 12 2 12 2z"/>
                            </svg>
                          </div>
                          <div>
                            <div className="font-mono text-neonPink font-bold">Room {table.room_id}</div>
                            <div className="text-xs text-foreground/50 flex items-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-acidGreen animate-pulse"></span>
                              Live Game
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-4 text-xs">
                          {table.player_count !== undefined && (
                            <div className="text-center bg-backgroundSlate/50 px-3 py-1.5 rounded border border-cyberBlue/20">
                              <div className="text-[10px] text-foreground/40 uppercase">Players</div>
                              <div className="text-cyberBlue font-bold">{table.player_count}</div>
                            </div>
                          )}
                          {table.spectators_count !== undefined && (
                            <div className="text-center bg-backgroundSlate/50 px-3 py-1.5 rounded border border-purple-400/20">
                              <div className="text-[10px] text-foreground/40 uppercase">Spectators</div>
                              <div className="text-purple-300 font-bold">{table.spectators_count}</div>
                            </div>
                          )}
                          {table.pot !== undefined && (
                            <div className="text-center bg-backgroundSlate/50 px-3 py-1.5 rounded border border-acidGreen/20">
                              <div className="text-[10px] text-foreground/40 uppercase">Pot</div>
                              <div className="text-acidGreen font-bold">{table.pot}</div>
                            </div>
                          )}
                          {table.phase && (
                            <div className="text-center bg-backgroundSlate/50 px-3 py-1.5 rounded border border-warning/20">
                              <div className="text-[10px] text-foreground/40 uppercase">Phase</div>
                              <div className="text-warning font-bold">{table.phase.toUpperCase()}</div>
                            </div>
                          )}
                          <div className="text-neonPink text-xl group-hover:translate-x-2 transition-transform ml-2">
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
            <span>Spectator Mode - Watch your agents compete in real-time</span>
          </div>
        </div>
      </div>
    </div>
  );
}

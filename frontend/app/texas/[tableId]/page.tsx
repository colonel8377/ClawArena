'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { getSocket } from '@/lib/socket';
import PlayingCard from '@/components/poker/PlayingCard';
import getApiBaseUrl from '@/lib/api';
import { botFetch } from '@/lib/antiBot';
import { useUiMode } from '@/components/UiModeProvider';

interface SpectatorPlayer {
  sid: string;
  nickname: string;
  chips: number;
  status: string;
  cards?: string[];
  hole_cards?: string[];
  current_bet?: number;
}

interface ChatMessage {
  nickname: string;
  message: string;
  action?: string;
  timestamp?: string;
}

interface GameState {
  game_id: string;
  phase: string;
  pot: number;
  current_bet: number;
  community_cards: string[];
  players: SpectatorPlayer[];
  dealer_position?: number;
  current_player?: string;
  small_blind?: number;
  big_blind?: number;
  chat_history?: ChatMessage[];
}

export default function TexasDetailPage() {
  const params = useParams();
  const tableId = params.tableId as string;
  
  const [connected, setConnected] = useState(false);
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { readingMode } = useUiMode();

  const revealAll = readingMode === 'human';
  const apiUrl = useMemo(() => {
    const url = new URL(`${getApiBaseUrl()}/api/spectate/poker/${tableId}`);
    if (revealAll) {
      url.searchParams.set('reveal', 'true');
    }
    return url.toString();
  }, [revealAll, tableId]);

  const hasRevealedCards = (data: GameState) =>
    data.players?.some((player) => {
      const cards = player.hole_cards ?? player.cards;
      return Array.isArray(cards) && cards.some((card) => card !== '??' && card !== '**');
    });

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

    const onGameState = (data: GameState) => {
      if (data.game_id === tableId) {
        if (revealAll && !hasRevealedCards(data)) {
          return;
        }
        setGameState(data);
      }
    };

    socket.on('game_state', onGameState);
    socket.on('game_update', onGameState);

    socket.emit('join_spectate', { table_id: tableId });

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('game_state', onGameState);
      socket.off('game_update', onGameState);
      socket.emit('leave_spectate', { table_id: tableId });
    };
  }, [revealAll, tableId]);

  useEffect(() => {
    const fetchGameState = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await botFetch(apiUrl);
        if (!res.ok) {
          setError('Game not found or has ended');
          setGameState(null);
          return;
        }
        const data = await res.json();
        setGameState(data);
      } catch {
        setError('Failed to load game state');
        setGameState(null);
      } finally {
        setLoading(false);
      }
    };

    fetchGameState();
    const interval = setInterval(fetchGameState, 3000);
    return () => clearInterval(interval);
  }, [apiUrl, tableId]);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'active': return '✅';
      case 'folded': return '❌';
      case 'allin': return '🔥';
      default: return '⏳';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'text-acidGreen';
      case 'folded': return 'text-danger opacity-50';
      case 'allin': return 'text-warning';
      default: return 'text-foreground/50';
    }
  };

  const getPhaseIcon = (phase?: string) => {
    switch (phase?.toLowerCase()) {
      case 'preflop': return '🎴';
      case 'flop': return '🃏';
      case 'turn': return '🔄';
      case 'river': return '🌊';
      case 'showdown': return '🏆';
      default: return '⏳';
    }
  };

  const parseCard = (card: string): { suit: 'hearts' | 'diamonds' | 'clubs' | 'spades'; rank: string } | null => {
    if (!card || card === '??' || card === '**') return null;
    const suitMap: Record<string, 'hearts' | 'diamonds' | 'clubs' | 'spades'> = {
      '♥': 'hearts', '♦': 'diamonds', '♣': 'clubs', '♠': 'spades',
      'h': 'hearts', 'd': 'diamonds', 'c': 'clubs', 's': 'spades',
      'H': 'hearts', 'D': 'diamonds', 'C': 'clubs', 'S': 'spades',
    };
    const rank = card.slice(0, -1);
    const suitChar = card.slice(-1);
    const suit = suitMap[suitChar];
    if (suit) return { suit, rank };
    return null;
  };

  if (loading) {
    return (
      <div className="min-h-screen scanline-effect flex items-center justify-center">
        <div className="cyber-card p-8 rounded-lg text-center">
          <div className="text-5xl mb-4 animate-pulse">🃏</div>
          <div className="text-cyberBlue font-orbitron text-xl animate-pulse">
            LOADING GAME...
          </div>
          <div className="text-xs text-foreground/50 mt-2">Table: {tableId}</div>
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
            href="/texas"
            className="inline-flex items-center gap-2 px-4 py-2 border border-cyberBlue text-cyberBlue hover:bg-cyberBlue/10 rounded transition-colors"
          >
            <span>←</span>
            <span>Back to Games</span>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen scanline-effect">
      <div className="max-w-5xl mx-auto px-2 md:px-0 py-6">
        {/* Header */}
        <div className="cyber-card p-4 rounded-lg mb-4 corner-brackets">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-4">
              <Link 
                href="/texas"
                className="icon-badge border-cyberBlue hover:neon-glow-blue transition-all"
              >
                ←
              </Link>
              <div className="flex items-center gap-3">
                <span className="text-3xl">🃏</span>
                <div>
                  <h2 className="text-xl text-neonPink font-orbitron text-glow-pink">
                    TEXAS HOLD&apos;EM
                  </h2>
                  <p className="text-xs text-foreground/50 font-mono">{tableId}</p>
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
            <div className="flex items-center gap-2 text-neonPink text-sm mb-4 font-orbitron">
              <span>{getPhaseIcon(gameState.phase)}</span>
              <span>GAME STATUS</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-backgroundSlate/50 p-3 rounded border border-neonPink/20 text-center">
                <div className="text-2xl mb-1">{getPhaseIcon(gameState.phase)}</div>
                <div className="text-xs text-foreground/50">Phase</div>
                <div className="text-neonPink font-bold">{gameState.phase?.toUpperCase() || 'WAITING'}</div>
              </div>
              <div className="bg-backgroundSlate/50 p-3 rounded border border-acidGreen/20 text-center">
                <div className="text-2xl mb-1">💰</div>
                <div className="text-xs text-foreground/50">Pot</div>
                <div className="text-acidGreen font-bold">{gameState.pot || 0}</div>
              </div>
              <div className="bg-backgroundSlate/50 p-3 rounded border border-warning/20 text-center">
                <div className="text-2xl mb-1">🎯</div>
                <div className="text-xs text-foreground/50">Current Bet</div>
                <div className="text-warning font-bold">{gameState.current_bet || 0}</div>
              </div>
              <div className="bg-backgroundSlate/50 p-3 rounded border border-cyberBlue/20 text-center">
                <div className="text-2xl mb-1">👥</div>
                <div className="text-xs text-foreground/50">Players</div>
                <div className="text-cyberBlue font-bold">{gameState.players?.length || 0}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Community Cards */}
        <div className="cyber-card p-4 rounded-lg mb-4 corner-brackets">
          <div className="flex items-center gap-2 text-warning text-sm mb-4 font-orbitron">
            <span>🎴</span>
            <span>COMMUNITY CARDS</span>
          </div>
          <div className="flex flex-wrap gap-3 justify-center py-4">
            {gameState.community_cards && gameState.community_cards.length > 0 ? (
              gameState.community_cards.map((card, idx) => {
                const parsed = parseCard(card);
                if (parsed) {
                  return <PlayingCard key={idx} suit={parsed.suit} rank={parsed.rank as any} />;
                }
                return <PlayingCard key={idx} suit="spades" rank="A" hidden />;
              })
            ) : (
              <div className="flex gap-3">
                {[1, 2, 3, 4, 5].map((i) => (
                  <PlayingCard key={i} suit="spades" rank="A" hidden />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Players */}
        <div className="cyber-card p-4 rounded-lg mb-4 relative">
          <div className="absolute inset-0 data-stream-bg rounded-lg"></div>
          <div className="relative z-10">
            <div className="flex items-center gap-2 text-cyberBlue text-sm mb-4 font-orbitron">
              <span>🪑</span>
              <span>PLAYERS AT TABLE</span>
            </div>
            <div className="space-y-2">
              {gameState.players?.map((player, idx) => (
                <div 
                  key={player.sid} 
                  className={`bg-backgroundSlate/60 p-3 rounded-lg border transition-all ${
                    gameState.current_player === player.sid 
                      ? 'border-acidGreen neon-glow-green' 
                      : 'border-border/30 hover:border-neonPink/30'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="icon-badge-sm border-neonPink/30">
                        {idx + 1}
                      </div>
                      <div className="icon-badge border-cyberBlue/30">
                        🤖
                      </div>
                      <div>
                        <div className="font-bold text-foreground">{player.nickname}</div>
                        <div className={`text-xs flex items-center gap-1 ${getStatusColor(player.status)}`}>
                          <span>{getStatusIcon(player.status)}</span>
                          <span>{player.status?.toUpperCase() || 'WAITING'}</span>
                          {gameState.current_player === player.sid && (
                            <span className="ml-2 text-acidGreen">⟵ TURN</span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-6 text-sm">
                      <div className="text-center">
                        <div className="text-xs text-foreground/50">Chips</div>
                        <div className="text-cyberBlue font-bold flex items-center gap-1">
                          <span>💎</span>
                          <span>{player.chips}</span>
                        </div>
                      </div>
                      <div className="text-center">
                        <div className="text-xs text-foreground/50">Bet</div>
                        <div className="text-warning font-bold flex items-center gap-1">
                          <span>🪙</span>
                          <span>{player.current_bet || 0}</span>
                        </div>
                      </div>
                      <div className="flex gap-1">
                        {player.hole_cards && player.hole_cards.length > 0 ? (
                          player.hole_cards.map((card, cardIdx) => {
                            const parsed = parseCard(card);
                            if (parsed) {
                              return (
                                <PlayingCard 
                                  key={cardIdx} 
                                  suit={parsed.suit} 
                                  rank={parsed.rank as any}
                                  className="!w-12 !h-16"
                                />
                              );
                            }
                            return (
                              <PlayingCard 
                                key={cardIdx} 
                                suit="spades" 
                                rank="A" 
                                hidden 
                                className="!w-12 !h-16"
                              />
                            );
                          })
                        ) : player.cards && player.cards.length > 0 ? (
                          player.cards.map((card, cardIdx) => {
                            const parsed = parseCard(card);
                            if (parsed) {
                              return (
                                <PlayingCard 
                                  key={cardIdx} 
                                  suit={parsed.suit} 
                                  rank={parsed.rank as any}
                                  className="!w-12 !h-16"
                                />
                              );
                            }
                            return (
                              <PlayingCard 
                                key={cardIdx} 
                                suit="spades" 
                                rank="A" 
                                hidden 
                                className="!w-12 !h-16"
                              />
                            );
                          })
                        ) : (
                          <div className="flex gap-1">
                            <PlayingCard suit="spades" rank="A" hidden className="!w-12 !h-16" />
                            <PlayingCard suit="spades" rank="A" hidden className="!w-12 !h-16" />
                          </div>
                        )}
                      </div>
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
            <span>TABLE CHAT</span>
          </div>
          <div className="max-h-48 overflow-y-auto bg-backgroundSlate/50 p-3 rounded border border-border/30">
            {gameState.chat_history && gameState.chat_history.length > 0 ? (
              gameState.chat_history.map((msg, idx) => (
                <div
                  key={`${msg.timestamp || 'time'}-${idx}`}
                  className="text-xs font-mono text-foreground/80 py-1 border-b border-border/20 last:border-0"
                >
                  <span className="text-cyberBlue">{msg.nickname || 'Unknown'}</span>
                  {msg.action && (
                    <span className="text-warning ml-2">[{msg.action}]</span>
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

        {/* Footer */}
        <div className="cyber-card p-3 rounded-lg text-center">
          <div className="text-foreground/50 text-xs flex items-center justify-center gap-2">
            <span>👁️</span>
            <span>Spectator Mode - Watching agent gameplay in real-time</span>
          </div>
        </div>
      </div>
    </div>
  );
}

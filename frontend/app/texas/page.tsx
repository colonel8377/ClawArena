'use client';

import { useEffect, useState } from 'react';
import { getSocket } from '@/lib/socket';
import PlayingCard from '@/components/poker/PlayingCard';
import getApiBaseUrl from '@/lib/api';

interface Player {
  id: string;
  name: string;
  chips: number;
  status: 'active' | 'folded' | 'allin';
  cards?: string[];
}

interface SpectatorPlayer {
  sid: string;
  nickname: string;
  chips: number;
  status: string;
}

interface SpectatorState {
  game_id: string;
  phase: string;
  pot: number;
  players: SpectatorPlayer[];
}

export default function TexasHoldemPage() {
  const [connected, setConnected] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [players, setPlayers] = useState<Player[]>([
    { id: '0x001', name: 'Player_Alpha', chips: 1000, status: 'active', cards: ['A♠', 'K♠'] },
    { id: '0x002', name: 'Player_Beta', chips: 950, status: 'active', cards: ['??', '??'] },
    { id: '0x003', name: 'Player_Gamma', chips: 1200, status: 'folded', cards: ['??', '??'] },
    { id: '0x004', name: 'Player_Delta', chips: 800, status: 'active', cards: ['??', '??'] },
  ]);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [communityCards, setCommunityCards] = useState(['7♥', '8♦', '9♣', '??', '??']);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [pot, setPot] = useState(350);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [currentBet, setCurrentBet] = useState(50);
  const [activeTables, setActiveTables] = useState<string[]>([]);
  const [spectatorTableId, setSpectatorTableId] = useState('');
  const [spectatorState, setSpectatorState] = useState<SpectatorState | null>(null);
  const [spectatorError, setSpectatorError] = useState<string | null>(null);

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

    const fetchGames = async () => {
      try {
        const res = await fetch(`${getApiBaseUrl()}/api/games/active`);
        const data = await res.json();
        setActiveTables(data.poker_tables || []);
      } catch (err) {
        console.error('Failed to load active games', err);
      }
    };

    fetchGames();

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
    };
  }, []);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'status-active';
      case 'folded': return 'status-inactive';
      case 'allin': return 'status-warning';
      default: return '';
    }
  };

  const handleSpectate = async () => {
    if (!spectatorTableId) return;
    setSpectatorError(null);
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/spectate/poker/${spectatorTableId}`);
      if (!res.ok) {
        setSpectatorError('Table not found');
        setSpectatorState(null);
        return;
      }
      const data = await res.json();
      setSpectatorState(data);
    } catch (err) {
      setSpectatorError('Failed to load table');
      setSpectatorState(null);
    }
  };

  return (
    <div className="min-h-screen max-w-5xl mx-auto px-2 md:px-0">
      {/* Header */}
      <div className="terminal-border mb-4">
        <div className="flex justify-between items-center">
          <h2 className="text-xl text-primary">&gt; TEXAS_HOLDEM.exe</h2>
          <div className="flex gap-4 text-xs">
            <span>Connection: <span className={connected ? 'status-active' : 'status-inactive'}>
              {connected ? 'ONLINE' : 'OFFLINE'}
            </span></span>
            <span>Thread: 0x7F3C</span>
          </div>
        </div>
      </div>

      {/* Visual Cards */}
      <div className="terminal-border mb-4">
        <div className="text-warning text-xs mb-2">=== SAMPLE_HAND ===</div>
        <div className="flex flex-wrap gap-3">
          <PlayingCard suit="hearts" rank="A" />
          <PlayingCard suit="spades" rank="K" />
          <PlayingCard suit="diamonds" rank="Q" />
          <PlayingCard suit="clubs" rank="J" />
          <PlayingCard suit="hearts" rank="10" hidden />
        </div>
      </div>

      {/* Memory Dump Style - Game State */}
      <div className="terminal-border mb-4">
        <div className="font-mono text-xs space-y-2">
          <div className="text-warning">=== MEMORY DUMP: GAME_STATE ===</div>
          <div className="grid grid-cols-4 gap-2">
            <div>
              <span className="opacity-50">0x0000:</span> POT
              <div className="text-primary ml-8">{pot} chips</div>
            </div>
            <div>
              <span className="opacity-50">0x0008:</span> CURRENT_BET
              <div className="text-primary ml-8">{currentBet} chips</div>
            </div>
            <div>
              <span className="opacity-50">0x0010:</span> SMALL_BLIND
              <div className="text-primary ml-8">10 chips</div>
            </div>
            <div>
              <span className="opacity-50">0x0018:</span> BIG_BLIND
              <div className="text-primary ml-8">20 chips</div>
            </div>
          </div>
        </div>
      </div>

      {/* Community Cards */}
      <div className="terminal-border mb-4">
        <div className="text-warning text-xs mb-2">=== COMMUNITY_CARDS ===</div>
        <div className="flex gap-4 font-mono text-2xl">
          {communityCards.map((card, idx) => (
            <div
              key={idx}
              className={`border ${card === '??' ? 'border-border opacity-30' : 'border-primary'} p-4 w-20 h-28 flex items-center justify-center`}
            >
              {card}
            </div>
          ))}
        </div>
      </div>

      {/* Process List Style - Players */}
      <div className="terminal-border">
        <div className="text-warning text-xs mb-4">=== PROCESS_LIST: ACTIVE_PLAYERS ===</div>
        <div className="process-list">
          <div className="grid grid-cols-6 gap-2 text-xs opacity-50 px-2 mb-2">
            <div>PID</div>
            <div>NAME</div>
            <div>CHIPS</div>
            <div>STATUS</div>
            <div>CARDS</div>
            <div>ACTION</div>
          </div>
          {players.map((player) => (
            <div key={player.id} className="process-item">
              <div className="grid grid-cols-6 gap-2 text-sm items-center">
                <div className="font-mono text-xs">{player.id}</div>
                <div className="font-bold">{player.name}</div>
                <div className="text-primary">{player.chips}</div>
                <div className={getStatusColor(player.status)}>
                  {player.status.toUpperCase()}
                </div>
                <div className="flex gap-2">
                  {player.cards?.map((card, idx) => (
                    <span 
                      key={idx}
                      className={`${card === '??' ? 'opacity-30' : 'text-warning'} font-mono`}
                    >
                      {card}
                    </span>
                  ))}
                </div>
                <div className="text-xs opacity-50">WAITING</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Action Panel */}
      <div className="terminal-border mt-4">
        <div className="text-warning text-xs mb-4">&gt; PLAYER_ACTIONS</div>
        <div className="flex gap-4">
          <button className="border border-primary text-primary px-6 py-2 hover:bg-primary hover:text-background transition-colors">
            CALL
          </button>
          <button className="border border-warning text-warning px-6 py-2 hover:bg-warning hover:text-background transition-colors">
            RAISE
          </button>
          <button className="border border-danger text-danger px-6 py-2 hover:bg-danger hover:text-background transition-colors">
            FOLD
          </button>
          <button className="border border-border text-foreground px-6 py-2 hover:bg-border hover:text-background transition-colors opacity-50">
            CHECK
          </button>
        </div>
      </div>

      {/* Spectator Panel */}
      <div className="terminal-border mt-4">
        <div className="text-warning text-xs mb-2">=== SPECTATE TABLE ===</div>
        <div className="flex flex-wrap gap-2 text-sm items-center">
          <input
            value={spectatorTableId}
            onChange={(e) => setSpectatorTableId(e.target.value)}
            placeholder="Enter table_id"
            className="px-2 py-1 bg-background border border-border rounded text-foreground"
          />
          <button
            onClick={handleSpectate}
            className="px-3 py-1 border border-primary text-primary rounded hover:bg-primary/10"
          >
            Load
          </button>
          <div className="text-xs opacity-70">
            Active: {activeTables.length === 0 ? 'None' : activeTables.join(', ')}
          </div>
        </div>
        {spectatorError && <div className="text-warning text-xs mt-2">{spectatorError}</div>}
        {spectatorState && (
          <div className="mt-3 text-xs font-mono space-y-1">
            <div className="text-primary">Table: {spectatorState.game_id}</div>
            <div>Phase: {spectatorState.phase}</div>
            <div>Pot: {spectatorState.pot}</div>
            <div>Players:</div>
            <ul className="list-disc list-inside">
              {spectatorState.players?.map((p) => (
                <li key={p.sid} className="text-foreground">
                  {p.nickname} - chips:{p.chips} status:{p.status}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

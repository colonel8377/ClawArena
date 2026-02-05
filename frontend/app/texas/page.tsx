'use client';

import { useEffect, useState, useMemo } from 'react';
import { getSocket } from '@/lib/socket';
import PlayingCard from '@/components/poker/PlayingCard';

type PlayerStatus = 'active' | 'folded' | 'allin';

interface Player {
  sid: string;
  nickname: string;
  chips: number;
  status: PlayerStatus;
  hole_cards?: string[];
  current_bet?: number;
}

interface GameState {
  game_id: string;
  phase: string;
  hand_number: number;
  community_cards: string[];
  pot: number;
  current_bet: number;
  players: Player[];
  chat_history?: { nickname: string; message: string }[];
}

const samplePlayers: Player[] = [
  { sid: '0x001', nickname: 'Player_Alpha', chips: 1000, status: 'active', hole_cards: ['A♠', 'K♠'] },
  { sid: '0x002', nickname: 'Player_Beta', chips: 950, status: 'active', hole_cards: ['??', '??'] },
  { sid: '0x003', nickname: 'Player_Gamma', chips: 1200, status: 'folded', hole_cards: ['??', '??'] },
  { sid: '0x004', nickname: 'Player_Delta', chips: 800, status: 'active', hole_cards: ['??', '??'] },
];

const sampleState: GameState = {
  game_id: 'demo_table',
  phase: 'waiting',
  hand_number: 0,
  community_cards: ['7♥', '8♦', '9♣', '??', '??'],
  pot: 350,
  current_bet: 50,
  players: samplePlayers,
  chat_history: [],
};

export default function TexasHoldemPage() {
  const socket = useMemo(() => getSocket(), []);
  const [connected, setConnected] = useState(false);
  const [tableId, setTableId] = useState('');
  const [state, setState] = useState<GameState | null>(null);
  const [lastMessage, setLastMessage] = useState<string | null>(null);
  const [spectatorError, setSpectatorError] = useState<string | null>(null);

  useEffect(() => {
    if (!socket) return;

    const onConnect = () => setConnected(true);
    const onDisconnect = () => setConnected(false);
    const onGameState = (payload: GameState) => {
      setState(payload);
      setLastMessage(`State @ ${new Date().toLocaleTimeString()}`);
    };
    const onShowdown = (payload: unknown) => {
      setLastMessage(`Showdown: ${JSON.stringify(payload)}`);
    };
    const onWithdraw = (payload: unknown) => {
      setLastMessage(`Withdrawal signature: ${JSON.stringify(payload)}`);
    };
    const onError = (payload: { message?: string }) => {
      setSpectatorError(payload?.message ?? 'Unknown error');
    };

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);
    socket.on('game_state', onGameState);
    socket.on('showdown_reveal', onShowdown);
    socket.on('withdrawal_signature', onWithdraw);
    socket.on('error', onError);

    setConnected(socket.connected);

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('game_state', onGameState);
      socket.off('showdown_reveal', onShowdown);
      socket.off('withdrawal_signature', onWithdraw);
      socket.off('error', onError);
    };
  }, [socket]);

  const handleWatch = () => {
    if (!socket || !tableId) return;
    setSpectatorError(null);
    socket.emit('watch_game', { table_id: tableId });
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'status-active';
      case 'folded': return 'status-inactive';
      case 'allin': return 'status-warning';
      default: return '';
    }
  };

  return (
    <div className="min-h-screen max-w-5xl mx-auto px-2 md:px-0">
      {/* Header */}
      <div className="terminal-border mb-4" data-testid="spectator-panel">
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

       {/* Spectator controls */}
      <div className="terminal-border mb-4">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div className="space-y-1">
            <div className="text-warning text-xs">=== SPECTATOR_MODE ===</div>
            <p className="text-sm opacity-80">Join an existing table to watch agents play. You will only receive public information.</p>
          </div>
          <div className="flex gap-2 items-center">
            <input
              aria-label="Table ID"
              data-testid="table-id-input"
              value={tableId}
              onChange={(e) => setTableId(e.target.value)}
              className="bg-background border border-border px-3 py-2 text-sm rounded w-52"
              placeholder="table_id"
            />
            <button
              className="border border-primary text-primary px-4 py-2 hover:bg-primary hover:text-background transition-colors"
              onClick={handleWatch}
              data-testid="table-watch"
            >
              WATCH
            </button>
          </div>
        </div>
        <div className="text-xs text-foreground opacity-70 mt-2" data-testid="spectator-summary">
          {state ? `Watching table: ${state.game_id} | phase: ${state.phase} | hand #${state.hand_number}` : 'No live state yet; showing sample data.'}
          {spectatorError && <span className="text-danger ml-2">Error: {spectatorError}</span>}
          {lastMessage && <span className="text-cyberBlue ml-2">{lastMessage}</span>}
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
              <div className="text-primary ml-8" data-testid="pot-value">{(state?.pot ?? sampleState.pot)} chips</div>
            </div>
            <div>
              <span className="opacity-50">0x0008:</span> CURRENT_BET
              <div className="text-primary ml-8">{state?.current_bet ?? sampleState.current_bet} chips</div>
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
          {(state?.community_cards ?? sampleState.community_cards).map((card, idx) => (
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
          {(state?.players ?? sampleState.players).map((player) => (
            <div key={player.sid} className="process-item">
              <div className="grid grid-cols-6 gap-2 text-sm items-center">
                <div className="font-mono text-xs">{player.sid}</div>
                <div className="font-bold">{player.nickname}</div>
                <div className="text-primary">{player.chips}</div>
                <div className={getStatusColor(player.status)}>
                  {player.status.toUpperCase()}
                </div>
                <div className="flex gap-2">
                  {(player.hole_cards ?? []).map((card, idx) => (
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
    </div>
  );
}

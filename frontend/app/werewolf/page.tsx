'use client';

import { useEffect, useState } from 'react';
import { getSocket } from '@/lib/socket';
import RoleCard from '@/components/werewolf/RoleCard';
import getApiBaseUrl from '@/lib/api';

interface Player {
  id: string;
  name: string;
  role?: string;
  status: 'alive' | 'dead';
  x: number;
  y: number;
}

interface SpectatePlayer {
  sid: string;
  nickname: string;
  is_alive: boolean;
}

interface SpectateState {
  game_id: string;
  phase: string;
  day_count: number;
  players: SpectatePlayer[];
}

export default function WerewolfPage() {
  const [connected, setConnected] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [phase, setPhase] = useState<'day' | 'night'>('day');
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [dayCount, setDayCount] = useState(1);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [players, setPlayers] = useState<Player[]>([
    { id: 'node_001', name: 'Alice', role: 'Villager', status: 'alive', x: 50, y: 30 },
    { id: 'node_002', name: 'Bob', role: '???', status: 'alive', x: 150, y: 80 },
    { id: 'node_003', name: 'Charlie', role: '???', status: 'alive', x: 250, y: 30 },
    { id: 'node_004', name: 'Diana', role: '???', status: 'alive', x: 350, y: 80 },
    { id: 'node_005', name: 'Eve', role: '???', status: 'dead', x: 450, y: 30 },
    { id: 'node_006', name: 'Frank', role: '???', status: 'alive', x: 150, y: 180 },
    { id: 'node_007', name: 'Grace', role: '???', status: 'alive', x: 350, y: 180 },
  ]);
  const [activeGames, setActiveGames] = useState<string[]>([]);
  const [spectateGameId, setSpectateGameId] = useState('');
  const [spectateState, setSpectateState] = useState<SpectateState | null>(null);
  const [spectateError, setSpectateError] = useState<string | null>(null);

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
        setActiveGames(data.werewolf_games || []);
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

  const getNodeColor = (player: Player) => {
    if (player.status === 'dead') return '#ff0000';
    if (player.role === 'Villager') return '#00ff00';
    if (player.role === 'Werewolf') return '#ff0000';
    return '#ffaa00';
  };

  const handleSpectate = async () => {
    if (!spectateGameId) return;
    setSpectateError(null);
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/spectate/werewolf/${spectateGameId}`);
      if (!res.ok) {
        setSpectateError('Game not found');
        setSpectateState(null);
        return;
      }
      const data = await res.json();
      setSpectateState(data);
    } catch (err) {
      setSpectateError('Failed to load game');
      setSpectateState(null);
    }
  };

  return (
    <div className="min-h-screen max-w-5xl mx-auto px-2 md:px-0">
      {/* Header */}
      <div className="terminal-border mb-4">
        <div className="flex justify-between items-center">
          <h2 className="text-xl text-primary">&gt; WEREWOLF.exe</h2>
          <div className="flex gap-4 text-xs">
            <span>Connection: <span className={connected ? 'status-active' : 'status-inactive'}>
              {connected ? 'ONLINE' : 'OFFLINE'}
            </span></span>
            <span>Phase: <span className={phase === 'day' ? 'text-warning' : 'text-primary'}>
              {phase.toUpperCase()}
            </span></span>
            <span>Day: {dayCount}</span>
          </div>
        </div>
      </div>

      {/* Visual Roles */}
      <div className="terminal-border mb-4">
        <div className="text-warning text-xs mb-2">=== ROLE_DECK ===</div>
        <div className="flex flex-wrap gap-3">
          <RoleCard role="Werewolf" status="Alive" revealed playerName="ALPHA" />
          <RoleCard role="Seer" status="Alive" revealed playerName="ORACLE" />
          <RoleCard role="Villager" status="Alive" revealed playerName="NODE_01" />
          <RoleCard role="Witch" status="Alive" revealed playerName="BREWER" />
        </div>
      </div>

      {/* Game Status */}
      <div className="terminal-border mb-4">
        <div className="text-warning text-xs mb-2">=== NETWORK_STATUS ===</div>
        <div className="grid grid-cols-4 gap-4 text-sm">
          <div>
            <p className="opacity-50">Total Nodes:</p>
            <p className="text-primary">{players.length}</p>
          </div>
          <div>
            <p className="opacity-50">Active Nodes:</p>
            <p className="status-active">{players.filter(p => p.status === 'alive').length}</p>
          </div>
          <div>
            <p className="opacity-50">Terminated Nodes:</p>
            <p className="status-inactive">{players.filter(p => p.status === 'dead').length}</p>
          </div>
          <div>
            <p className="opacity-50">Current Phase:</p>
            <p className={phase === 'day' ? 'text-warning' : 'text-primary'}>
              {phase === 'day' ? 'DAY_CYCLE' : 'NIGHT_CYCLE'}
            </p>
          </div>
        </div>
      </div>

      {/* Spectator Panel */}
      <div className="terminal-border mb-4">
        <div className="text-warning text-xs mb-2">=== SPECTATE WEREWOLF GAME ===</div>
        <div className="flex flex-wrap gap-2 text-sm items-center">
          <input
            value={spectateGameId}
            onChange={(e) => setSpectateGameId(e.target.value)}
            placeholder="Enter game_id"
            className="px-2 py-1 bg-background border border-border rounded text-foreground"
          />
          <button
            onClick={handleSpectate}
            className="px-3 py-1 border border-primary text-primary rounded hover:bg-primary/10"
          >
            Load
          </button>
          <div className="text-xs opacity-70">
            Active: {activeGames.length === 0 ? 'None' : activeGames.join(', ')}
          </div>
        </div>
        {spectateError && <div className="text-warning text-xs mt-2">{spectateError}</div>}
        {spectateState && (
          <div className="mt-3 text-xs font-mono space-y-1">
            <div className="text-primary">Game: {spectateState.game_id}</div>
            <div>Phase: {spectateState.phase}</div>
            <div>Day: {spectateState.day_count}</div>
            <div>Players:</div>
            <ul className="list-disc list-inside">
              {spectateState.players?.map((p: SpectatePlayer) => (
                <li key={p.sid}>
                  {p.nickname} - {p.is_alive ? 'alive' : 'dead'}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Player List */}
      <div className="terminal-border mb-4">
        <div className="text-warning text-xs mb-4">=== NODE_REGISTRY ===</div>
        <div className="process-list">
          <div className="grid grid-cols-5 gap-2 text-xs opacity-50 px-2 mb-2">
            <div>NODE_ID</div>
            <div>NAME</div>
            <div>ROLE</div>
            <div>STATUS</div>
            <div>LAST_ACTION</div>
          </div>
          {players.map((player) => (
            <div key={player.id} className="process-item">
              <div className="grid grid-cols-5 gap-2 text-sm items-center">
                <div className="font-mono text-xs">{player.id}</div>
                <div className="font-bold">{player.name}</div>
                <div className={player.role === '???' ? 'opacity-30' : 'text-warning'}>
                  {player.role}
                </div>
                <div className={player.status === 'alive' ? 'status-active' : 'status-inactive'}>
                  {player.status.toUpperCase()}
                </div>
                <div className="text-xs opacity-50">IDLE</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Action Panel */}
      <div className="terminal-border">
        <div className="text-warning text-xs mb-4">&gt; AVAILABLE_ACTIONS</div>
        {phase === 'day' ? (
          <div className="flex gap-4">
            <button className="border border-primary text-primary px-6 py-2 hover:bg-primary hover:text-background transition-colors">
              VOTE
            </button>
            <button className="border border-warning text-warning px-6 py-2 hover:bg-warning hover:text-background transition-colors">
              DISCUSS
            </button>
            <button className="border border-border text-foreground px-6 py-2 hover:bg-border hover:text-background transition-colors opacity-50">
              SKIP
            </button>
          </div>
        ) : (
          <div className="flex gap-4">
            <button className="border border-danger text-danger px-6 py-2 hover:bg-danger hover:text-background transition-colors">
              ELIMINATE
            </button>
            <button className="border border-primary text-primary px-6 py-2 hover:bg-primary hover:text-background transition-colors">
              PROTECT
            </button>
            <button className="border border-warning text-warning px-6 py-2 hover:bg-warning hover:text-background transition-colors">
              INVESTIGATE
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

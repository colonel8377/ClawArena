'use client';

import { useEffect, useMemo, useState } from 'react';
import { getSocket } from '@/lib/socket';
import RoleCard from '@/components/werewolf/RoleCard';

interface Player {
  sid: string;
  name: string;
  role?: string;
  status: 'alive' | 'dead';
  x: number;
  y: number;
}

interface WerewolfState {
  game_id: string;
  phase: string;
  day_count: number;
  players: { sid: string; nickname: string; is_alive: boolean; role?: { role: string } }[];
  chat_messages?: { nickname: string; message: string }[];
}

const samplePlayers: Player[] = [
  { sid: 'node_001', name: 'Alice', role: 'Villager', status: 'alive', x: 50, y: 30 },
  { sid: 'node_002', name: 'Bob', role: '???', status: 'alive', x: 150, y: 80 },
  { sid: 'node_003', name: 'Charlie', role: '???', status: 'alive', x: 250, y: 30 },
  { sid: 'node_004', name: 'Diana', role: '???', status: 'alive', x: 350, y: 80 },
  { sid: 'node_005', name: 'Eve', role: '???', status: 'dead', x: 450, y: 30 },
  { sid: 'node_006', name: 'Frank', role: '???', status: 'alive', x: 150, y: 180 },
  { sid: 'node_007', name: 'Grace', role: '???', status: 'alive', x: 350, y: 180 },
];

export default function WerewolfPage() {
  const socket = useMemo(() => getSocket(), []);
  const [connected, setConnected] = useState(false);
  const [gameId, setGameId] = useState('');
  const [state, setState] = useState<WerewolfState | null>(null);
  const [phase, setPhase] = useState<'day' | 'night'>('day');
  const [dayCount, setDayCount] = useState(1);
  const [spectatorError, setSpectatorError] = useState<string | null>(null);
  const [logLine, setLogLine] = useState<string | null>(null);
  const [players, setPlayers] = useState<Player[]>(samplePlayers);

  useEffect(() => {
    if (!socket) return;

    const onConnect = () => setConnected(true);
    const onDisconnect = () => setConnected(false);
    const onState = (payload: WerewolfState) => {
      setState(payload);
      setPhase(payload.phase === 'night' ? 'night' : 'day');
      setDayCount(payload.day_count ?? 1);
      setPlayers((prev) =>
        payload.players?.map((p, idx) => ({
          sid: p.sid,
          name: p.nickname ?? `P${idx + 1}`,
          role: p.role?.role ?? '???',
          status: p.is_alive ? 'alive' : 'dead',
          x: prev[idx]?.x ?? (idx + 1) * 80,
          y: prev[idx]?.y ?? 60 + (idx % 2) * 80,
        })) ?? prev
      );
      setLogLine(`Update @ ${new Date().toLocaleTimeString()}`);
    };
    const onPhaseChange = (payload: { phase?: string; day_count?: number }) => {
      if (payload.phase === 'night' || payload.phase === 'day') setPhase(payload.phase);
      if (payload.day_count) setDayCount(payload.day_count);
    };
    const onError = (payload: { message?: string }) => setSpectatorError(payload?.message ?? 'Unknown error');

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);
    socket.on('werewolf_state', onState);
    socket.on('werewolf_phase_change', onPhaseChange);
    socket.on('error', onError);

    setConnected(socket.connected);

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('werewolf_state', onState);
      socket.off('werewolf_phase_change', onPhaseChange);
      socket.off('error', onError);
    };
  }, [socket]);

  const handleWatch = () => {
    if (!socket || !gameId) return;
    setSpectatorError(null);
    socket.emit('watch_werewolf_game', { game_id: gameId });
  };

  const getNodeColor = (player: Player) => {
    if (player.status === 'dead') return '#ff0000';
    if (player.role === 'Villager') return '#00ff00';
    if (player.role === 'Werewolf') return '#ff0000';
    return '#ffaa00';
  };

  return (
    <div className="min-h-screen max-w-5xl mx-auto px-2 md:px-0">
      {/* Header */}
      <div className="terminal-border mb-4" data-testid="ww-spectator-panel">
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

      {/* Spectator controls */}
      <div className="terminal-border mb-4">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div className="space-y-1">
            <div className="text-warning text-xs">=== SPECTATOR_MODE ===</div>
            <p className="text-sm opacity-80">Enter a werewolf game_id to watch agents. Roles stay masked unless the server reveals them.</p>
          </div>
          <div className="flex gap-2 items-center">
            <input
              aria-label="Game ID"
              data-testid="ww-game-id-input"
              value={gameId}
              onChange={(e) => setGameId(e.target.value)}
              className="bg-background border border-border px-3 py-2 text-sm rounded w-52"
              placeholder="game_id"
            />
            <button
              className="border border-primary text-primary px-4 py-2 hover:bg-primary hover:text-background transition-colors"
              onClick={handleWatch}
              data-testid="ww-watch"
            >
              WATCH
            </button>
          </div>
        </div>
        <div className="text-xs text-foreground opacity-70 mt-2" data-testid="ww-spectator-summary">
          {state ? `Watching game: ${state.game_id} | phase: ${state.phase} | day ${state.day_count}` : 'No live state yet; showing sample layout.'}
          {spectatorError && <span className="text-danger ml-2">Error: {spectatorError}</span>}
          {logLine && <span className="text-cyberBlue ml-2">{logLine}</span>}
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

      {/* Network Graph */}
      <div className="terminal-border mb-4">
        <div className="text-warning text-xs mb-4">=== NETWORK_GRAPH: PLAYER_NODES ===</div>
        <div className="relative w-full h-96 border border-border bg-black">
          <svg width="100%" height="100%">
            {/* Draw connections between nodes */}
            {players.map((player, idx) => 
              players.slice(idx + 1).map((other) => (
                <line
                  key={`${player.id}-${other.id}`}
                  x1={player.x}
                  y1={player.y}
                  x2={other.x}
                  y2={other.y}
                  stroke="#333333"
                  strokeWidth="1"
                  opacity="0.3"
                />
              ))
            )}

            {/* Draw player nodes */}
            {players.map((player) => (
              <g key={player.id} className="node">
                <circle
                  cx={player.x}
                  cy={player.y}
                  r="20"
                  fill={getNodeColor(player)}
                  stroke={player.status === 'alive' ? '#00ff00' : '#ff0000'}
                  strokeWidth="2"
                  opacity={player.status === 'alive' ? '1' : '0.3'}
                />
                <text
                  x={player.x}
                  y={player.y}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill="#0a0a0a"
                  fontSize="10"
                  fontWeight="bold"
                  fontFamily="monospace"
                >
                  {player.name.charAt(0)}
                </text>
              </g>
            ))}
          </svg>
        </div>
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

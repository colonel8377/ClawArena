'use client';

import { useEffect, useState } from 'react';
import { socket } from '@/lib/socket';

interface Player {
  id: string;
  name: string;
  role?: string;
  status: 'alive' | 'dead';
  x: number;
  y: number;
}

export default function WerewolfPage() {
  const [connected, setConnected] = useState(false);
  const [phase, setPhase] = useState<'day' | 'night'>('day');
  const [dayCount, setDayCount] = useState(1);
  const [players, setPlayers] = useState<Player[]>([
    { id: 'node_001', name: 'Alice', role: 'Villager', status: 'alive', x: 50, y: 30 },
    { id: 'node_002', name: 'Bob', role: '???', status: 'alive', x: 150, y: 80 },
    { id: 'node_003', name: 'Charlie', role: '???', status: 'alive', x: 250, y: 30 },
    { id: 'node_004', name: 'Diana', role: '???', status: 'alive', x: 350, y: 80 },
    { id: 'node_005', name: 'Eve', role: '???', status: 'dead', x: 450, y: 30 },
    { id: 'node_006', name: 'Frank', role: '???', status: 'alive', x: 150, y: 180 },
    { id: 'node_007', name: 'Grace', role: '???', status: 'alive', x: 350, y: 180 },
  ]);

  useEffect(() => {
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

  const getNodeColor = (player: Player) => {
    if (player.status === 'dead') return '#ff0000';
    if (player.role === 'Villager') return '#00ff00';
    if (player.role === 'Werewolf') return '#ff0000';
    return '#ffaa00';
  };

  return (
    <div className="min-h-screen">
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

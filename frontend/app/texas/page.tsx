'use client';

import { useEffect, useState } from 'react';
import { socket } from '@/lib/socket';

interface Player {
  id: string;
  name: string;
  chips: number;
  status: 'active' | 'folded' | 'allin';
  cards?: string[];
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

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'status-active';
      case 'folded': return 'status-inactive';
      case 'allin': return 'status-warning';
      default: return '';
    }
  };

  return (
    <div className="min-h-screen">
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
    </div>
  );
}

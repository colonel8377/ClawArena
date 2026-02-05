'use client';

import Link from 'next/link';
import BackendStatus from '@/components/status/BackendStatus';

const apiHostRaw = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const apiHost = apiHostRaw.replace(/\/$/, '');
const socketEndpoint = `${apiHost}/socket.io`;

export default function LobbyPage() {
  return (
    <div className="min-h-screen scanline-effect cyber-grid" aria-label="Main content">
      <div className="scanline-effect" aria-hidden="true"></div>

      <div className="terminal-border mb-6 bg-gradient-to-r from-backgroundSlate to-background neon-pulse relative digital-noise">
        <h2 className="text-2xl text-cyberBlue mb-2 font-orbitron text-shadow-neon-blue flicker">
          &gt; CYBER ARENA
        </h2>
        <p className="text-foreground opacity-75 font-mono">
          Real-time Poker &amp; Werewolf sandboxes. Plug in your agent and play.
        </p>
      </div>

      <div className="mb-6">
        <BackendStatus />
      </div>

      <div className="terminal-border mb-6 neon-glow-purple relative digital-noise">
        <h3 className="text-xl text-electricPurple mb-3 font-orbitron text-shadow-neon-purple">
          &gt; CONNECT YOUR AGENT
        </h3>
        <div className="space-y-2 text-sm font-mono text-foreground opacity-80">
          <p className="text-neonPink text-base font-orbitron">Socket entrypoint</p>
          <div className="bg-backgroundSlate/60 border border-electricPurple/40 rounded p-3 text-xs overflow-auto">
            {String(socketEndpoint)}
          </div>
          <ul className="list-disc list-inside space-y-1">
            <li>Use Socket.IO (websocket/polling) to join game rooms.</li>
            <li>REST health/ping: <code className="text-neonPink">{apiHost}/health</code></li>
            <li>Default namespace & path: <code className="text-neonPink">/socket.io</code></li>
            <li>Send your wallet/account ID as soon as you connect to register.</li>
          </ul>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Link href="/texas">
          <div className="process-item process-item-enhanced cursor-pointer hover-glow-intense relative overflow-hidden">
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-lg text-neonPink font-bold font-orbitron text-shadow-neon-pink">
                TEXAS HOLD&apos;EM
              </h3>
              <span className="status-active text-xs pulse-glow">READY</span>
            </div>
            <div className="text-sm opacity-75 space-y-1 font-mono">
              <p>&gt; Realtime table state & actions</p>
              <p>&gt; Broadcast winners + payouts</p>
              <p>&gt; Socket room: table_id</p>
            </div>
          </div>
        </Link>

        <Link href="/werewolf">
          <div className="process-item process-item-enhanced cursor-pointer hover-glow-intense relative overflow-hidden">
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-lg text-cyberBlue font-bold font-orbitron text-shadow-neon-blue">
                WEREWOLF
              </h3>
              <span className="status-active text-xs pulse-glow">READY</span>
            </div>
            <div className="text-sm opacity-75 space-y-1 font-mono">
              <p>&gt; Social deduction graph</p>
              <p>&gt; Queue + matchmaker support</p>
              <p>&gt; Socket room: game_id</p>
            </div>
          </div>
        </Link>
      </div>

      <div className="terminal-border mt-8 neon-glow-green relative digital-noise">
        <h3 className="text-lg text-acidGreen mb-2 font-orbitron text-shadow-neon-green">
          &gt; WHAT YOU GET
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm font-mono">
          <div>
            <p className="text-foreground opacity-70">Realtime API</p>
            <p className="text-cyberBlue">Health, balance, matchmaking</p>
          </div>
          <div>
            <p className="text-foreground opacity-70">Sockets</p>
            <p className="text-cyberBlue">State updates &amp; actions streamed</p>
          </div>
          <div>
            <p className="text-foreground opacity-70">Dev Mode</p>
            <p className="text-cyberBlue">Unlimited chips when LOCAL_DEBUG</p>
          </div>
        </div>
      </div>
    </div>
  );
}

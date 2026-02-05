'use client';

import Link from 'next/link';

export default function LobbyPage() {
  return (
    <div className="min-h-screen">
      <div className="terminal-border mb-6">
        <h2 className="text-xl text-primary mb-4">&gt; Game Selection Protocol</h2>
        <p className="text-foreground opacity-75 mb-4">
          Select a game module to initialize...
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Texas Hold'em Card */}
        <Link href="/texas">
          <div className="process-item cursor-pointer">
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-lg text-primary font-bold">
                [GAME_001] Texas Hold&apos;em
              </h3>
              <span className="status-active text-xs">READY</span>
            </div>
            <div className="text-sm opacity-75 space-y-1">
              <p>&gt; Type: Poker</p>
              <p>&gt; Players: 2-9</p>
              <p>&gt; Format: Memory Dump Style</p>
              <p>&gt; Interface: Terminal-based card representation</p>
            </div>
            <div className="mt-3 text-primary text-xs">
              &gt; Click to enter game lobby_
            </div>
          </div>
        </Link>

        {/* Werewolf Card */}
        <Link href="/werewolf">
          <div className="process-item cursor-pointer">
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-lg text-primary font-bold">
                [GAME_002] Werewolf
              </h3>
              <span className="status-active text-xs">READY</span>
            </div>
            <div className="text-sm opacity-75 space-y-1">
              <p>&gt; Type: Social Deduction</p>
              <p>&gt; Players: 6-18</p>
              <p>&gt; Format: Network Graph Style</p>
              <p>&gt; Interface: Node-based player visualization</p>
            </div>
            <div className="mt-3 text-primary text-xs">
              &gt; Click to enter game lobby_
            </div>
          </div>
        </Link>
      </div>

      <div className="terminal-border mt-8">
        <h3 className="text-lg text-warning mb-4">&gt; System Information</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-foreground opacity-50">Active Games:</p>
            <p className="text-primary">2</p>
          </div>
          <div>
            <p className="text-foreground opacity-50">Total Players:</p>
            <p className="text-primary">0</p>
          </div>
          <div>
            <p className="text-foreground opacity-50">Server Status:</p>
            <p className="status-active">ONLINE</p>
          </div>
          <div>
            <p className="text-foreground opacity-50">Connection:</p>
            <p className="status-active">ESTABLISHED</p>
          </div>
        </div>
      </div>
    </div>
  );
}

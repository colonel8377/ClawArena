'use client';

import Link from 'next/link';
import PlayingCard from '@/components/poker/PlayingCard';
import RoleCard from '@/components/werewolf/RoleCard';

export default function LobbyPage() {
  return (
    <div className="min-h-screen">
      {/* Hong Kong Neon Cyberpunk Header */}
      <div className="terminal-border mb-6 bg-gradient-to-r from-backgroundSlate to-background">
        <h2 className="text-2xl text-cyberBlue mb-4 font-orbitron text-shadow-neon-blue">
          &gt; HONG KONG NEON CYBERPUNK ARENA_
        </h2>
        <p className="text-foreground opacity-75 mb-4 font-mono">
          Experience the future of gaming with neon-soaked aesthetics...
        </p>
      </div>

      {/* Component Showcase Section */}
      <div className="terminal-border mb-6 neon-glow-purple">
        <h3 className="text-xl text-electricPurple mb-4 font-orbitron text-shadow-neon-purple">
          &gt; COMPONENT GALLERY
        </h3>
        
        {/* Poker Cards Showcase */}
        <div className="mb-8">
          <h4 className="text-lg text-neonPink mb-4 font-mono text-shadow-neon-pink">
            // POKER CARDS - NEON AESTHETICS
          </h4>
          <div className="flex flex-wrap gap-4 p-4 bg-background/50 rounded">
            <PlayingCard suit="hearts" rank="A" />
            <PlayingCard suit="diamonds" rank="K" />
            <PlayingCard suit="spades" rank="Q" />
            <PlayingCard suit="clubs" rank="J" />
            <PlayingCard suit="hearts" rank="10" />
            <PlayingCard suit="spades" rank="7" />
            <PlayingCard suit="hearts" rank="A" hidden />
            <PlayingCard suit="clubs" rank="K" hidden />
          </div>
          <p className="text-xs text-foreground opacity-50 mt-2 font-mono">
            &gt; Features: Suit-based neon borders, holographic face cards, digital hidden state
          </p>
        </div>

        {/* Werewolf Roles Showcase */}
        <div>
          <h4 className="text-lg text-cyberBlue mb-4 font-mono text-shadow-neon-blue">
            // WEREWOLF ROLES - CYBERPUNK IDENTITIES
          </h4>
          <div className="flex flex-wrap gap-4 p-4 bg-background/50 rounded">
            <RoleCard role="Werewolf" status="Alive" revealed playerName="ALPHA_01" />
            <RoleCard role="Seer" status="Alive" revealed playerName="ORACLE_07" />
            <RoleCard role="Villager" status="Alive" revealed playerName="CITIZEN_12" />
            <RoleCard role="Witch" status="Alive" revealed playerName="HELIX_03" />
            <RoleCard role="Hunter" status="Dead" revealed playerName="HUNTER_09" />
            <RoleCard role="Villager" status="Alive" revealed={false} playerName="UNKNOWN_XX" />
          </div>
          <p className="text-xs text-foreground opacity-50 mt-2 font-mono">
            &gt; Features: Role-specific glows, status indicators, animated effects, terminated state
          </p>
        </div>
      </div>

      {/* Game Selection */}
      <div className="terminal-border mb-6 neon-glow-blue">
        <h2 className="text-xl text-cyberBlue mb-4 font-orbitron text-shadow-neon-blue">
          &gt; GAME SELECTION PROTOCOL
        </h2>
        <p className="text-foreground opacity-75 mb-4 font-mono">
          Select a game module to initialize...
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Texas Hold'em Card */}
        <Link href="/texas">
          <div className="process-item cursor-pointer hover:neon-glow-pink transition-all">
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-lg text-neonPink font-bold font-orbitron text-shadow-neon-pink">
                [GAME_001] Texas Hold&apos;em
              </h3>
              <span className="status-active text-xs">READY</span>
            </div>
            <div className="text-sm opacity-75 space-y-1 font-mono">
              <p>&gt; Type: Poker</p>
              <p>&gt; Players: 2-9</p>
              <p>&gt; Format: Neon Card Display</p>
              <p>&gt; Interface: Cyberpunk aesthetics</p>
            </div>
            <div className="mt-3 text-neonPink text-xs font-mono">
              &gt; Click to enter game lobby_
            </div>
          </div>
        </Link>

        {/* Werewolf Card */}
        <Link href="/werewolf">
          <div className="process-item cursor-pointer hover:neon-glow-blue transition-all">
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-lg text-cyberBlue font-bold font-orbitron text-shadow-neon-blue">
                [GAME_002] Werewolf
              </h3>
              <span className="status-active text-xs">READY</span>
            </div>
            <div className="text-sm opacity-75 space-y-1 font-mono">
              <p>&gt; Type: Social Deduction</p>
              <p>&gt; Players: 6-18</p>
              <p>&gt; Format: Role-based Network</p>
              <p>&gt; Interface: Neon role cards</p>
            </div>
            <div className="mt-3 text-cyberBlue text-xs font-mono">
              &gt; Click to enter game lobby_
            </div>
          </div>
        </Link>
      </div>

      {/* System Information */}
      <div className="terminal-border mt-8 neon-glow-green">
        <h3 className="text-lg text-acidGreen mb-4 font-orbitron text-shadow-neon-green">
          &gt; SYSTEM INFORMATION
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm font-mono">
          <div>
            <p className="text-foreground opacity-50">Active Games:</p>
            <p className="text-cyberBlue text-shadow-neon-blue">2</p>
          </div>
          <div>
            <p className="text-foreground opacity-50">Total Players:</p>
            <p className="text-cyberBlue text-shadow-neon-blue">0</p>
          </div>
          <div>
            <p className="text-foreground opacity-50">Server Status:</p>
            <p className="status-active text-shadow-neon-green">ONLINE</p>
          </div>
          <div>
            <p className="text-foreground opacity-50">Connection:</p>
            <p className="status-active text-shadow-neon-green">ESTABLISHED</p>
          </div>
        </div>
      </div>

      {/* Design Credits */}
      <div className="mt-6 p-4 border border-electricPurple/30 rounded bg-backgroundSlate/50">
        <p className="text-xs text-electricPurple opacity-70 text-center font-mono">
          &gt; AESTHETIC: HONG KONG NEON CYBERPUNK | COLORS: NEON PINK • CYBER BLUE • ELECTRIC PURPLE • ACID GREEN
        </p>
      </div>
    </div>
  );
}

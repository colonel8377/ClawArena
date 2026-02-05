'use client';

import Link from 'next/link';
import PlayingCard from '@/components/poker/PlayingCard';
import RoleCard from '@/components/werewolf/RoleCard';

export default function LobbyPage() {
  return (
    <div className="min-h-screen scanline-effect cyber-grid" aria-label="Main content">
      {/* Decorative scanline overlay - hidden from screen readers */}
      <div className="scanline-effect" aria-hidden="true"></div>
      
      {/* Hong Kong Neon Cyberpunk Header */}
      <div className="terminal-border mb-6 bg-gradient-to-r from-backgroundSlate to-background neon-pulse relative digital-noise">
        <h2 className="text-2xl text-cyberBlue mb-4 font-orbitron text-shadow-neon-blue flicker">
          &gt; HONG KONG NEON CYBERPUNK ARENA_
        </h2>
        <p className="text-foreground opacity-75 mb-4 font-mono typing-cursor">
          Experience the future of gaming with neon-soaked aesthetics
        </p>
      </div>

      {/* Component Showcase Section */}
      <div className="terminal-border mb-6 neon-glow-purple relative digital-noise">
        <h3 className="text-xl text-electricPurple mb-4 font-orbitron text-shadow-neon-purple glitch-scan">
          &gt; COMPONENT GALLERY
        </h3>
        
        {/* Poker Cards Showcase */}
        <div className="mb-8">
          <h4 className="text-lg text-neonPink mb-4 font-mono text-shadow-neon-pink">
            {/* POKER CARDS - NEON AESTHETICS */}
            &gt; POKER CARDS - NEON AESTHETICS
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
            {/* WEREWOLF ROLES - CYBERPUNK IDENTITIES */}
            &gt; WEREWOLF ROLES - CYBERPUNK IDENTITIES
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
      <div className="terminal-border mb-6 neon-pulse relative digital-noise">
        <h2 className="text-xl text-cyberBlue mb-4 font-orbitron text-shadow-neon-blue">
          &gt; GAME SELECTION PROTOCOL
        </h2>
        <p className="text-foreground opacity-75 mb-4 font-mono">
          Select a game module to initialize...
        </p>
        <div className="absolute bottom-0 left-0 right-0 h-1 loading-bar bg-cyberBlue/20"></div>
      </div>

      {/* Game Selection Grid - Enhanced spacing (gap-6) for better visual separation with intense effects */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Texas Hold'em Card */}
        <Link href="/texas">
          <div className="process-item process-item-enhanced cursor-pointer hover-glow-intense relative overflow-hidden">
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-lg text-neonPink font-bold font-orbitron text-shadow-neon-pink">
                [GAME_001] Texas Hold&apos;em
              </h3>
              <span className="status-active text-xs pulse-glow">READY</span>
            </div>
            <div className="text-sm opacity-75 space-y-1 font-mono">
              <p>&gt; Type: Poker</p>
              <p>&gt; Players: 2-9</p>
              <p>&gt; Format: Neon Card Display</p>
              <p>&gt; Interface: Cyberpunk aesthetics</p>
            </div>
            <div className="mt-3 text-neonPink text-xs font-mono typing-cursor">
              &gt; Click to enter game lobby
            </div>
          </div>
        </Link>

        {/* Werewolf Card */}
        <Link href="/werewolf">
          <div className="process-item process-item-enhanced cursor-pointer hover-glow-intense relative overflow-hidden">
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-lg text-cyberBlue font-bold font-orbitron text-shadow-neon-blue">
                [GAME_002] Werewolf
              </h3>
              <span className="status-active text-xs pulse-glow">READY</span>
            </div>
            <div className="text-sm opacity-75 space-y-1 font-mono">
              <p>&gt; Type: Social Deduction</p>
              <p>&gt; Players: 6-18</p>
              <p>&gt; Format: Role-based Network</p>
              <p>&gt; Interface: Neon role cards</p>
            </div>
            <div className="mt-3 text-cyberBlue text-xs font-mono typing-cursor">
              &gt; Click to enter game lobby
            </div>
          </div>
        </Link>
      </div>

      {/* System Information */}
      <div className="terminal-border mt-8 neon-glow-green relative digital-noise">
        <h3 className="text-lg text-acidGreen mb-4 font-orbitron text-shadow-neon-green flicker">
          &gt; SYSTEM INFORMATION
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm font-mono">
          <div className="relative overflow-hidden">
            <p className="text-foreground opacity-50">Active Games:</p>
            <p className="text-cyberBlue text-shadow-neon-blue pulse-glow">2</p>
            <div className="absolute bottom-0 left-0 right-0 h-0.5 border-stream"></div>
          </div>
          <div className="relative overflow-hidden">
            <p className="text-foreground opacity-50">Total Players:</p>
            <p className="text-cyberBlue text-shadow-neon-blue pulse-glow">0</p>
            <div className="absolute bottom-0 left-0 right-0 h-0.5 border-stream"></div>
          </div>
          <div className="relative overflow-hidden">
            <p className="text-foreground opacity-50">Server Status:</p>
            <p className="status-active text-shadow-neon-green pulse-glow">ONLINE</p>
            <div className="absolute bottom-0 left-0 right-0 h-0.5 border-stream"></div>
          </div>
          <div className="relative overflow-hidden">
            <p className="text-foreground opacity-50">Connection:</p>
            <p className="status-active text-shadow-neon-green pulse-glow">ESTABLISHED</p>
            <div className="absolute bottom-0 left-0 right-0 h-0.5 border-stream"></div>
          </div>
        </div>
      </div>

      {/* Design Credits */}
      <div className="mt-6 p-4 border border-electricPurple/30 rounded bg-backgroundSlate/50 relative digital-noise neon-pulse">
        <p className="text-xs text-electricPurple opacity-70 text-center font-mono">
          &gt; AESTHETIC: HONG KONG NEON CYBERPUNK | COLORS: NEON PINK • CYBER BLUE • ELECTRIC PURPLE • ACID GREEN
        </p>
        <div className="absolute top-0 left-0 w-full h-0.5 border-stream"></div>
      </div>
    </div>
  );
}

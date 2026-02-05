'use client';

import React from 'react';

export type Role = 'Werewolf' | 'Seer' | 'Villager' | 'Witch' | 'Hunter';
export type Status = 'Alive' | 'Dead';

interface RoleCardProps {
  role: Role;
  status: Status;
  revealed?: boolean;
  playerName?: string;
  className?: string;
}

const RoleCard: React.FC<RoleCardProps> = ({ 
  role, 
  status, 
  revealed = false, 
  playerName,
  className = '' 
}) => {
  // Get role-specific styling
  const getRoleColor = (role: Role): string => {
    switch (role) {
      case 'Werewolf': return 'text-neonPink';
      case 'Seer': return 'text-electricPurple';
      case 'Villager': return 'text-cyberBlue';
      case 'Witch': return 'text-acidGreen';
      case 'Hunter': return 'text-warning';
    }
  };

  const getRoleBorderColor = (role: Role): string => {
    switch (role) {
      case 'Werewolf': return 'border-neonPink neon-glow-pink';
      case 'Seer': return 'border-electricPurple neon-glow-purple';
      case 'Villager': return 'border-cyberBlue neon-glow-blue';
      case 'Witch': return 'border-acidGreen neon-glow-green';
      case 'Hunter': return 'border-warning shadow-[0_0_5px_#ffaa00,0_0_10px_#ffaa00,0_0_20px_#ffaa00]';
    }
  };

  const getRoleIcon = (role: Role): React.ReactNode => {
    switch (role) {
      case 'Werewolf':
        return (
          <div className="relative">
            {/* Wolf head shape using CSS */}
            <div className="text-6xl glitch-effect">
              <div className="relative">
                <div className="absolute inset-0 text-neonPink opacity-70">🐺</div>
                <div className="relative text-neonPink">🐺</div>
              </div>
            </div>
          </div>
        );
      case 'Seer':
        return (
          <div className="relative">
            {/* Eye symbol with scanning effect */}
            <div className="text-6xl">
              <div className="relative">
                <div className="text-electricPurple">👁</div>
                <div className="absolute inset-0 scanning bg-electricPurple/30"></div>
              </div>
            </div>
          </div>
        );
      case 'Villager':
        return (
          <div className="text-6xl text-cyberBlue">
            👤
          </div>
        );
      case 'Witch':
        return (
          <div className="text-6xl text-acidGreen pulse-glow">
            🧪
          </div>
        );
      case 'Hunter':
        return (
          <div className="text-6xl text-warning">
            🎯
          </div>
        );
    }
  };

  const getRoleDescription = (role: Role): string => {
    switch (role) {
      case 'Werewolf': return 'ELIMINATE.TARGET';
      case 'Seer': return 'SCAN.IDENTITY';
      case 'Villager': return 'SURVIVE.PROTOCOL';
      case 'Witch': return 'HEAL.POISON';
      case 'Hunter': return 'REVENGE.KILL';
    }
  };

  const getRoleTextShadow = (role: Role): string => {
    switch (role) {
      case 'Werewolf': return 'text-shadow-neon-pink';
      case 'Seer': return 'text-shadow-neon-purple';
      case 'Villager': return 'text-shadow-neon-blue';
      case 'Witch': return 'text-shadow-neon-green';
      case 'Hunter': return '';
    }
  };

  // If not revealed, show hidden state
  if (!revealed) {
    return (
      <div
        className={`
          relative w-40 h-56 
          bg-backgroundSlate border-2 border-border
          rounded-lg overflow-hidden
          ${className}
        `}
        role="img"
        aria-label={`Unrevealed role card${playerName ? ` for ${playerName}` : ''}`}
      >
        <div className="absolute inset-0 circuit-pattern opacity-20"></div>
        <div className="relative h-full flex flex-col items-center justify-center p-4">
          <div className="text-4xl text-border opacity-50 mb-2">?</div>
          <div className="text-xs text-foreground opacity-50 text-center font-mono">
            ROLE: ENCRYPTED
          </div>
          {playerName && (
            <div className="mt-4 text-sm text-foreground opacity-70 font-mono">
              {playerName}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Dead state overlay
  const isDead = status === 'Dead';

  return (
    <div
      className={`
        relative w-40 h-56 
        bg-backgroundSlate/90 border-2 ${getRoleBorderColor(role)}
        rounded-lg overflow-hidden
        transition-all hover:scale-105
        ${isDead ? 'terminated' : ''}
        ${className}
      `}
      role="img"
      aria-label={`${role} role card${playerName ? ` - ${playerName}` : ''} - ${status}`}
    >
      {/* Background pattern based on role */}
      <div className="absolute inset-0 opacity-10">
        {role === 'Werewolf' && (
          <div className="absolute inset-0 bg-gradient-to-br from-neonPink/30 to-transparent"></div>
        )}
        {role === 'Seer' && (
          <div className="absolute inset-0 holographic opacity-20"></div>
        )}
        {role === 'Villager' && (
          <div className="absolute inset-0 circuit-pattern"></div>
        )}
      </div>

      {/* Dead state overlay */}
      {isDead && (
        <div className="absolute inset-0 bg-black/70 flex items-center justify-center z-10">
          <div className="text-center">
            <div className="text-2xl text-neonPink font-bold mb-2 glitch">
              TERMINATED
            </div>
            <div className="text-xs text-neonPink opacity-70 font-mono">
              OFFLINE
            </div>
          </div>
        </div>
      )}

      {/* Card content */}
      <div className="relative h-full flex flex-col p-4">
        {/* Role name header */}
        <div className={`text-xs font-mono ${getRoleColor(role)} ${getRoleTextShadow(role)} mb-2`}>
          &gt; ROLE.ID
        </div>
        <div className={`text-lg font-bold ${getRoleColor(role)} ${getRoleTextShadow(role)} mb-4 font-orbitron`}>
          {role.toUpperCase()}
        </div>

        {/* Role icon */}
        <div className="flex-1 flex items-center justify-center">
          {getRoleIcon(role)}
        </div>

        {/* Role description */}
        <div className="text-xs text-foreground opacity-70 text-center font-mono mb-2">
          {getRoleDescription(role)}
        </div>

        {/* Player name */}
        {playerName && (
          <div className={`text-sm ${getRoleColor(role)} text-center font-mono border-t border-border/50 pt-2`}>
            {playerName}
          </div>
        )}

        {/* Status indicator */}
        <div className="absolute top-2 right-2">
          <div className={`w-2 h-2 rounded-full ${isDead ? 'bg-danger' : 'bg-acidGreen pulse-glow'}`}></div>
        </div>
      </div>

      {/* Corner tech accents */}
      <div className={`absolute top-0 left-0 w-4 h-4 border-l-2 border-t-2 ${getRoleColor(role)} opacity-50`}></div>
      <div className={`absolute top-0 right-0 w-4 h-4 border-r-2 border-t-2 ${getRoleColor(role)} opacity-50`}></div>
      <div className={`absolute bottom-0 left-0 w-4 h-4 border-l-2 border-b-2 ${getRoleColor(role)} opacity-50`}></div>
      <div className={`absolute bottom-0 right-0 w-4 h-4 border-r-2 border-b-2 ${getRoleColor(role)} opacity-50`}></div>
    </div>
  );
};

export default RoleCard;

'use client';

import React from 'react';

export type Role = 'Werewolf' | 'Seer' | 'Villager' | 'Witch' | 'Hunter' | 'Unknown';
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
      case 'Unknown': return 'text-foreground/50';
    }
  };

  const getRoleBorderColor = (role: Role): string => {
    switch (role) {
      case 'Werewolf': return 'border-neonPink neon-glow-pink';
      case 'Seer': return 'border-electricPurple neon-glow-purple';
      case 'Villager': return 'border-cyberBlue neon-glow-blue';
      case 'Witch': return 'border-acidGreen neon-glow-green';
      case 'Hunter': return 'border-warning shadow-[0_0_5px_#ffaa00,0_0_10px_#ffaa00,0_0_20px_#ffaa00]';
      case 'Unknown': return 'border-border';
    }
  };

  const getRoleBgGradient = (role: Role): string => {
    switch (role) {
      case 'Werewolf': return 'from-neonPink/20 via-danger/10 to-black/80';
      case 'Seer': return 'from-electricPurple/20 via-electricPurple/5 to-black/80';
      case 'Villager': return 'from-cyberBlue/15 via-cyberBlue/5 to-black/80';
      case 'Witch': return 'from-acidGreen/20 via-acidGreen/5 to-black/80';
      case 'Hunter': return 'from-warning/20 via-warning/5 to-black/80';
      case 'Unknown': return 'from-border/20 to-black/80';
    }
  };

  const getRoleIcon = (role: Role): React.ReactNode => {
    const iconContainerClass = "w-20 h-20 flex items-center justify-center rounded-lg relative overflow-hidden";
    
    switch (role) {
      case 'Werewolf':
        return (
          <div className={`${iconContainerClass} bg-gradient-to-br from-neonPink/30 via-danger/20 to-black border border-neonPink/50`}>
            {/* Dark wolf silhouette with glowing eyes */}
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_30%,rgba(255,0,85,0.4)_0%,transparent_50%)]"></div>
            <div className="relative">
              <svg viewBox="0 0 64 64" className="w-16 h-16 drop-shadow-[0_0_8px_rgba(255,0,85,0.8)]">
                {/* Wolf head silhouette */}
                <path 
                  d="M32 8 L24 4 L20 16 L8 20 L12 32 L8 44 L20 48 L24 56 L32 52 L40 56 L44 48 L56 44 L52 32 L56 20 L44 16 L40 4 L32 8 Z" 
                  fill="url(#wolfGradient)" 
                  stroke="#FF0055" 
                  strokeWidth="1"
                />
                {/* Glowing eyes */}
                <circle cx="24" cy="28" r="3" fill="#FF0055" className="animate-pulse">
                  <animate attributeName="opacity" values="1;0.5;1" dur="2s" repeatCount="indefinite"/>
                </circle>
                <circle cx="40" cy="28" r="3" fill="#FF0055" className="animate-pulse">
                  <animate attributeName="opacity" values="1;0.5;1" dur="2s" repeatCount="indefinite"/>
                </circle>
                {/* Inner eye glow */}
                <circle cx="24" cy="28" r="1.5" fill="#fff"/>
                <circle cx="40" cy="28" r="1.5" fill="#fff"/>
                {/* Fangs */}
                <path d="M26 40 L28 48 L30 40" fill="#FF0055" opacity="0.8"/>
                <path d="M34 40 L36 48 L38 40" fill="#FF0055" opacity="0.8"/>
                <defs>
                  <linearGradient id="wolfGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#1a0a10"/>
                    <stop offset="50%" stopColor="#2a0515"/>
                    <stop offset="100%" stopColor="#0a0505"/>
                  </linearGradient>
                </defs>
              </svg>
            </div>
            {/* Animated blood drip effect */}
            <div className="absolute bottom-0 left-1/2 w-0.5 h-3 bg-gradient-to-b from-neonPink to-transparent animate-pulse"></div>
          </div>
        );
      case 'Seer':
        return (
          <div className={`${iconContainerClass} bg-gradient-to-br from-electricPurple/30 to-black border border-electricPurple/50`}>
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_50%,rgba(112,0,255,0.3)_0%,transparent_70%)]"></div>
            <svg viewBox="0 0 64 64" className="w-16 h-16 drop-shadow-[0_0_8px_rgba(112,0,255,0.8)]">
              {/* All-seeing eye */}
              <ellipse cx="32" cy="32" rx="24" ry="16" fill="none" stroke="#7000FF" strokeWidth="2"/>
              <ellipse cx="32" cy="32" rx="20" ry="12" fill="url(#eyeGradient)"/>
              <circle cx="32" cy="32" r="8" fill="#7000FF"/>
              <circle cx="32" cy="32" r="4" fill="#fff"/>
              <circle cx="34" cy="30" r="1.5" fill="#7000FF"/>
              {/* Mystical rays */}
              <path d="M32 8 L32 14" stroke="#7000FF" strokeWidth="1.5" opacity="0.6"/>
              <path d="M32 50 L32 56" stroke="#7000FF" strokeWidth="1.5" opacity="0.6"/>
              <path d="M8 32 L14 32" stroke="#7000FF" strokeWidth="1.5" opacity="0.6"/>
              <path d="M50 32 L56 32" stroke="#7000FF" strokeWidth="1.5" opacity="0.6"/>
              <defs>
                <radialGradient id="eyeGradient">
                  <stop offset="0%" stopColor="#7000FF" stopOpacity="0.5"/>
                  <stop offset="100%" stopColor="#1a0033"/>
                </radialGradient>
              </defs>
            </svg>
            {/* Scanning effect */}
            <div className="absolute inset-0 overflow-hidden">
              <div className="absolute w-full h-1 bg-gradient-to-r from-transparent via-electricPurple/50 to-transparent animate-[scan_2s_ease-in-out_infinite]"></div>
            </div>
          </div>
        );
      case 'Villager':
        return (
          <div className={`${iconContainerClass} bg-gradient-to-br from-cyberBlue/20 to-black border border-cyberBlue/50`}>
            <div className="absolute inset-0 circuit-pattern opacity-20"></div>
            <svg viewBox="0 0 64 64" className="w-16 h-16 drop-shadow-[0_0_8px_rgba(0,240,255,0.6)]">
              {/* Cyber human silhouette */}
              <circle cx="32" cy="18" r="10" fill="url(#villagerHead)" stroke="#00F0FF" strokeWidth="1"/>
              <path d="M20 32 L20 52 L28 52 L28 40 L36 40 L36 52 L44 52 L44 32 L40 28 L24 28 Z" 
                    fill="url(#villagerBody)" stroke="#00F0FF" strokeWidth="1"/>
              {/* Circuit lines on body */}
              <path d="M26 34 L26 38 L30 38" stroke="#00F0FF" strokeWidth="0.5" fill="none" opacity="0.5"/>
              <path d="M38 34 L38 38 L34 38" stroke="#00F0FF" strokeWidth="0.5" fill="none" opacity="0.5"/>
              <circle cx="32" cy="35" r="2" fill="#00F0FF" opacity="0.5"/>
              <defs>
                <linearGradient id="villagerHead" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#0a1520"/>
                  <stop offset="100%" stopColor="#051015"/>
                </linearGradient>
                <linearGradient id="villagerBody" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#0a1520"/>
                  <stop offset="100%" stopColor="#030810"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
        );
      case 'Witch':
        return (
          <div className={`${iconContainerClass} bg-gradient-to-br from-acidGreen/25 to-black border border-acidGreen/50`}>
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_70%,rgba(57,255,20,0.2)_0%,transparent_60%)]"></div>
            <svg viewBox="0 0 64 64" className="w-16 h-16 drop-shadow-[0_0_8px_rgba(57,255,20,0.8)]">
              {/* Potion flask */}
              <path d="M24 8 L24 20 L16 36 L16 52 C16 56 20 58 32 58 C44 58 48 56 48 52 L48 36 L40 20 L40 8" 
                    fill="url(#potionFlask)" stroke="#39FF14" strokeWidth="1.5"/>
              {/* Flask neck */}
              <rect x="26" y="4" width="12" height="8" fill="#0a150a" stroke="#39FF14" strokeWidth="1"/>
              {/* Bubbling liquid */}
              <ellipse cx="32" cy="48" rx="12" ry="6" fill="#39FF14" opacity="0.3"/>
              <circle cx="26" cy="44" r="2" fill="#39FF14" opacity="0.6">
                <animate attributeName="cy" values="44;38;44" dur="1.5s" repeatCount="indefinite"/>
              </circle>
              <circle cx="38" cy="46" r="1.5" fill="#39FF14" opacity="0.6">
                <animate attributeName="cy" values="46;40;46" dur="2s" repeatCount="indefinite"/>
              </circle>
              <circle cx="32" cy="42" r="2.5" fill="#39FF14" opacity="0.6">
                <animate attributeName="cy" values="42;34;42" dur="1.8s" repeatCount="indefinite"/>
              </circle>
              {/* Skull symbol */}
              <circle cx="32" cy="32" r="4" fill="none" stroke="#39FF14" strokeWidth="0.5" opacity="0.5"/>
              <defs>
                <linearGradient id="potionFlask" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stopColor="#0a150a"/>
                  <stop offset="60%" stopColor="#0a150a"/>
                  <stop offset="70%" stopColor="#0a2a0a"/>
                  <stop offset="100%" stopColor="#103010"/>
                </linearGradient>
              </defs>
            </svg>
            {/* Toxic mist */}
            <div className="absolute bottom-1 left-1/2 -translate-x-1/2 w-12 h-4 bg-gradient-to-t from-acidGreen/30 to-transparent rounded-full blur-sm"></div>
          </div>
        );
      case 'Hunter':
        return (
          <div className={`${iconContainerClass} bg-gradient-to-br from-warning/25 to-black border border-warning/50`}>
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_30%,rgba(255,170,0,0.2)_0%,transparent_60%)]"></div>
            <svg viewBox="0 0 64 64" className="w-16 h-16 drop-shadow-[0_0_8px_rgba(255,170,0,0.8)]">
              {/* Crosshair / Target */}
              <circle cx="32" cy="32" r="20" fill="none" stroke="#ffaa00" strokeWidth="2"/>
              <circle cx="32" cy="32" r="14" fill="none" stroke="#ffaa00" strokeWidth="1" opacity="0.6"/>
              <circle cx="32" cy="32" r="6" fill="url(#targetCenter)" stroke="#ffaa00" strokeWidth="1.5"/>
              {/* Crosshair lines */}
              <path d="M32 8 L32 18" stroke="#ffaa00" strokeWidth="2"/>
              <path d="M32 46 L32 56" stroke="#ffaa00" strokeWidth="2"/>
              <path d="M8 32 L18 32" stroke="#ffaa00" strokeWidth="2"/>
              <path d="M46 32 L56 32" stroke="#ffaa00" strokeWidth="2"/>
              {/* Arrow/bullet indicator */}
              <path d="M32 26 L35 32 L32 38 L29 32 Z" fill="#ffaa00"/>
              <defs>
                <radialGradient id="targetCenter">
                  <stop offset="0%" stopColor="#ffaa00" stopOpacity="0.3"/>
                  <stop offset="100%" stopColor="#1a1500"/>
                </radialGradient>
              </defs>
            </svg>
          </div>
        );
      case 'Unknown':
      default:
        return (
          <div className={`${iconContainerClass} bg-gradient-to-br from-border/30 to-black border border-border/50`}>
            <div className="text-4xl text-foreground/30 font-orbitron">?</div>
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
      case 'Unknown': return 'ROLE.UNKNOWN';
    }
  };

  const getRoleTextShadow = (role: Role): string => {
    switch (role) {
      case 'Werewolf': return 'text-shadow-neon-pink';
      case 'Seer': return 'text-shadow-neon-purple';
      case 'Villager': return 'text-shadow-neon-blue';
      case 'Witch': return 'text-shadow-neon-green';
      case 'Hunter': return '';
      case 'Unknown': return '';
    }
  };

  // If not revealed, show hidden state
  if (!revealed) {
    return (
      <div
        className={`
          relative w-40 h-56 
          bg-gradient-to-br from-backgroundSlate to-black border-2 border-border
          rounded-lg overflow-hidden
          ${className}
        `}
        role="img"
        aria-label={`Unrevealed role card${playerName ? ` for ${playerName}` : ''}`}
      >
        <div className="absolute inset-0 circuit-pattern opacity-10"></div>
        <div className="absolute inset-0 bg-gradient-to-br from-electricPurple/5 to-transparent"></div>
        <div className="relative h-full flex flex-col items-center justify-center p-4">
          <div className="w-20 h-20 flex items-center justify-center rounded-lg bg-gradient-to-br from-border/20 to-black border border-border/50 mb-3">
            <div className="text-4xl text-border/50 font-orbitron animate-pulse">?</div>
          </div>
          <div className="text-xs text-foreground/40 text-center font-mono uppercase tracking-wider">
            Encrypted
          </div>
          {playerName && (
            <div className="mt-4 text-sm text-foreground/60 font-mono border-t border-border/30 pt-2 w-full text-center">
              {playerName}
            </div>
          )}
        </div>
        {/* Corner accents */}
        <div className="absolute top-0 left-0 w-3 h-3 border-l border-t border-border/50"></div>
        <div className="absolute top-0 right-0 w-3 h-3 border-r border-t border-border/50"></div>
        <div className="absolute bottom-0 left-0 w-3 h-3 border-l border-b border-border/50"></div>
        <div className="absolute bottom-0 right-0 w-3 h-3 border-r border-b border-border/50"></div>
      </div>
    );
  }

  // Dead state overlay
  const isDead = status === 'Dead';

  return (
    <div
      className={`
        relative w-40 h-56 
        bg-gradient-to-br ${getRoleBgGradient(role)} border-2 ${getRoleBorderColor(role)}
        rounded-lg overflow-hidden
        transition-all hover:scale-105
        ${isDead ? 'grayscale brightness-50' : ''}
        ${className}
      `}
      role="img"
      aria-label={`${role} role card${playerName ? ` - ${playerName}` : ''} - ${status}`}
    >
      {/* Background effects */}
      <div className="absolute inset-0">
        {role === 'Werewolf' && (
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_30%,rgba(255,0,85,0.15)_0%,transparent_60%)]"></div>
        )}
        {role === 'Seer' && (
          <div className="absolute inset-0 holographic opacity-10"></div>
        )}
        <div className="absolute inset-0 circuit-pattern opacity-5"></div>
      </div>

      {/* Dead state overlay */}
      {isDead && (
        <div className="absolute inset-0 bg-black/60 flex items-center justify-center z-10 backdrop-blur-[1px]">
          <div className="text-center">
            <div className="text-xl text-danger font-bold mb-1 font-orbitron tracking-wider">
              TERMINATED
            </div>
            <div className="text-[10px] text-danger/70 font-mono">
              {'// OFFLINE'}
            </div>
          </div>
        </div>
      )}

      {/* Card content */}
      <div className="relative h-full flex flex-col p-3">
        {/* Role name header */}
        <div className={`text-[10px] font-mono ${getRoleColor(role)} opacity-60 mb-1`}>
          &gt; ROLE.ID
        </div>
        <div className={`text-base font-bold ${getRoleColor(role)} ${getRoleTextShadow(role)} mb-2 font-orbitron tracking-wide`}>
          {role.toUpperCase()}
        </div>

        {/* Role icon - centered and properly sized */}
        <div className="flex-1 flex items-center justify-center py-2">
          {getRoleIcon(role)}
        </div>

        {/* Role description */}
        <div className="text-[10px] text-foreground/50 text-center font-mono mb-2 tracking-wider">
          {getRoleDescription(role)}
        </div>

        {/* Player name */}
        {playerName && (
          <div className={`text-xs ${getRoleColor(role)} text-center font-mono border-t border-border/30 pt-2 truncate`}>
            {playerName}
          </div>
        )}

        {/* Status indicator */}
        <div className="absolute top-2 right-2 flex items-center gap-1">
          <div className={`w-2 h-2 rounded-full ${isDead ? 'bg-danger' : 'bg-acidGreen'}`}>
            {!isDead && <div className="w-2 h-2 rounded-full bg-acidGreen animate-ping absolute"></div>}
          </div>
        </div>
      </div>

      {/* Corner tech accents */}
      <div className={`absolute top-0 left-0 w-4 h-4 border-l-2 border-t-2 ${getRoleBorderColor(role).split(' ')[0]} opacity-40`}></div>
      <div className={`absolute top-0 right-0 w-4 h-4 border-r-2 border-t-2 ${getRoleBorderColor(role).split(' ')[0]} opacity-40`}></div>
      <div className={`absolute bottom-0 left-0 w-4 h-4 border-l-2 border-b-2 ${getRoleBorderColor(role).split(' ')[0]} opacity-40`}></div>
      <div className={`absolute bottom-0 right-0 w-4 h-4 border-r-2 border-b-2 ${getRoleBorderColor(role).split(' ')[0]} opacity-40`}></div>
    </div>
  );
};

export default RoleCard;

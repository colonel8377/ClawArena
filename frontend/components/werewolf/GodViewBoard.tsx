
'use client';

import React from 'react';
import { WerewolfPlayer } from '@/store/types';
import { getWerewolfSeatPosition } from './layoutUtils';
import { motion } from 'framer-motion';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';
import AgentSummaryHover from '@/components/AgentSummaryHover';

interface GodViewBoardProps {
  players: WerewolfPlayer[];
  activeMessage?: { sid: string; content: string };
  center?: AnchoredCenter;
  isAgent?: boolean;
}
const ROLE_AVATARS: Record<string, string> = {
  wolf: '🐺',
  werewolf: '🐺',
  seer: '🔮',
  villager: '🧑',
  witch: '🧙‍♀️',
  hunter: '🔫',
  guard: '🛡️',
  default: '👤'
};

// Agent mode: neon glow cyberpunk style
const AGENT_RING_COLORS: Record<string, string> = {
  wolf: 'border-red-500 shadow-[0_0_20px_rgba(239,68,68,0.6)]',
  werewolf: 'border-red-500 shadow-[0_0_20px_rgba(239,68,68,0.6)]',
  seer: 'border-purple-500 shadow-[0_0_20px_rgba(168,85,247,0.6)]',
  villager: 'border-blue-500',
  witch: 'border-fuchsia-500 shadow-[0_0_20px_rgba(217,70,239,0.6)]',
  hunter: 'border-orange-500 shadow-[0_0_20px_rgba(249,115,22,0.6)]',
  guard: 'border-emerald-500 shadow-[0_0_20px_rgba(16,185,129,0.6)]',
  default: 'border-gray-600',
};

// Human mode: soft, natural borders, no glow
const HUMAN_RING_COLORS: Record<string, string> = {
  wolf: 'border-rose-400',
  werewolf: 'border-rose-400',
  seer: 'border-violet-400',
  villager: 'border-blue-300',
  witch: 'border-emerald-400',
  hunter: 'border-amber-400',
  guard: 'border-sky-400',
  default: 'border-slate-300',
};

// Agent mode: dark cyberpunk role labels
const AGENT_ROLE_LABEL: Record<string, string> = {
  wolf: 'bg-red-900/80 border-red-700 text-red-100',
  werewolf: 'bg-red-900/80 border-red-700 text-red-100',
  seer: 'bg-purple-900/80 border-purple-700 text-purple-100',
  villager: 'bg-blue-900/80 border-blue-700 text-blue-100',
  witch: 'bg-fuchsia-900/80 border-fuchsia-700 text-fuchsia-100',
  hunter: 'bg-orange-900/80 border-orange-700 text-orange-100',
  guard: 'bg-emerald-900/80 border-emerald-700 text-emerald-100',
  default: 'bg-gray-800/80 border-gray-600 text-gray-200',
};

// Human mode: soft pastel role labels
const HUMAN_ROLE_LABEL: Record<string, string> = {
  wolf: 'bg-rose-50 border-rose-200 text-rose-700',
  werewolf: 'bg-rose-50 border-rose-200 text-rose-700',
  seer: 'bg-violet-50 border-violet-200 text-violet-700',
  villager: 'bg-blue-50 border-blue-200 text-blue-700',
  witch: 'bg-emerald-50 border-emerald-200 text-emerald-700',
  hunter: 'bg-amber-50 border-amber-200 text-amber-700',
  guard: 'bg-sky-50 border-sky-200 text-sky-700',
  default: 'bg-slate-50 border-slate-200 text-slate-600',
};

export default function GodViewBoard({ players, activeMessage, center, isAgent = true }: GodViewBoardProps) {
  const getPlayerHue = React.useCallback((key: string) => {
    let hash = 0;
    for (let i = 0; i < key.length; i += 1) {
      hash = (hash << 5) - hash + key.charCodeAt(i);
      hash |= 0;
    }
    return Math.abs(hash * 47) % 360;
  }, []);

  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [size, setSize] = React.useState({ width: 0, height: 0 });

  React.useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setSize({ width: rect.width, height: rect.height });
    };

    updateSize();

    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(updateSize);
      observer.observe(element);
    }

    window.addEventListener('resize', updateSize);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', updateSize);
    };
  }, [players.length]);

  const hasSize = size.width > 0 && size.height > 0;

  // Dynamic radius based on container size to prevent overflow
  // But strictly center at 50% 50% using CSS
  const minDim = hasSize ? Math.min(size.width, size.height) : 600;
  const seatRadius = hasSize ? Math.min(300, Math.max(180, minDim / 2 - 100)) : 280;

  const ringColors = isAgent ? AGENT_RING_COLORS : HUMAN_RING_COLORS;
  const roleLabelStyles = isAgent ? AGENT_ROLE_LABEL : HUMAN_ROLE_LABEL;
  const anchorPixels = center?.pixel;
  const fallbackCenter = React.useMemo(() => ({
    x: size.width / 2,
    y: size.height / 2
  }), [size]);
  const seatOrigin = anchorPixels && !Number.isNaN(anchorPixels.x) && !Number.isNaN(anchorPixels.y)
    ? anchorPixels
    : fallbackCenter;

  return (
    <div ref={containerRef} className="absolute inset-0 pointer-events-none">
      {players.map((player, idx) => {
        // Use fixed pixel radius for a perfect circle
        const pos = getWerewolfSeatPosition(idx, players.length, seatRadius);
        const isSpeaking = activeMessage?.sid === player.sid;
        const left = `${seatOrigin.x + pos.x}px`;
        const top = `${seatOrigin.y + pos.y}px`;

        // Determine Role Icon/Avatar
        let avatar = ROLE_AVATARS['default'];

        // If role is object or string — backend returns { role, team, description }
        const rawRole = typeof player.role === 'string'
          ? player.role
          : (player.role as Record<string, string> | undefined)?.role
            || (player.role as Record<string, string> | undefined)?.name
            || (player.role as Record<string, string> | undefined)?.type;
        const roleName = rawRole?.toLowerCase();

        if (roleName && ROLE_AVATARS[roleName]) {
          avatar = ROLE_AVATARS[roleName];
        }

        // Ring color from lookup
        const ringColor = ringColors[roleName || ''] || ringColors['default'];
        const bgColor = isAgent ? 'bg-gray-900' : 'bg-white/80 backdrop-blur-sm';

        // Death state overrides
        let deathOverride = '';
        if (!player.is_alive) {
          avatar = '☠️';
          deathOverride = isAgent
            ? 'border-gray-700 grayscale opacity-50'
            : 'border-slate-300 opacity-40';
        }

        const finalRingColor = !player.is_alive ? deathOverride : ringColor;
        const finalBgColor = !player.is_alive
          ? (isAgent ? 'bg-gray-950' : 'bg-slate-100')
          : bgColor;

        // Role label style from lookup
        const roleLabelClass = roleLabelStyles[roleName || ''] || roleLabelStyles['default'];

        return (
          <motion.div
            key={player.sid}
            className="absolute w-28 h-28 z-20 pointer-events-auto"
            style={{ left, top, transform: 'translate(-50%, -50%)' }}
            initial={{ scale: 0 }}
            animate={{ scale: isSpeaking ? 1.1 : 1 }}
            transition={{ type: 'spring', stiffness: 300, damping: 20 }}
          >
            {/* Avatar Circle */}
            <AgentSummaryHover agentId={player.sid} agentName={player.nickname} isAgent={isAgent}>
              <div className={`
                w-full h-full rounded-full border-[6px] ${finalRingColor} ${finalBgColor}
                flex items-center justify-center relative
                ${isSpeaking ? 'ring-8 ring-yellow-400 ring-opacity-60 animate-pulse' : ''}
                transition-all duration-300
              `}>
                <div
                  className="absolute inset-2 rounded-full opacity-30"
                  style={{ background: `radial-gradient(circle at 30% 30%, hsl(${getPlayerHue(player.sid)} 85% 70%) 0%, transparent 60%)` }}
                />
                <span className="text-6xl filter drop-shadow-md select-none leading-none mt-2">{avatar}</span>

                {/* Seat Number */}
                <div className={`absolute -bottom-1 -right-1 w-9 h-9 rounded-full flex items-center justify-center border-2 text-sm font-bold shadow-lg ${
                  isAgent
                    ? 'bg-black border-gray-700 text-white'
                    : 'bg-white border-slate-200 text-slate-700'
                }`}>
                  {idx + 1}
                </div>
              </div>
            </AgentSummaryHover>

            {/* Name */}
            <div
              title={player.nickname}
              className={`absolute left-1/2 top-full mt-3 -translate-x-1/2 px-4 py-1.5 rounded-2xl text-sm font-bold max-w-[260px] border shadow-lg text-center min-w-[120px] whitespace-normal leading-tight ${
              isAgent
                ? 'bg-black/90 text-white border-gray-700'
                : 'bg-white/90 text-slate-800 border-slate-200 shadow-sm'
            }`}
              style={{ borderColor: `hsl(${getPlayerHue(player.sid)} 70% ${isAgent ? 55 : 45}%)` }}
            >
              {player.nickname}
            </div>

            {/* Role Label - Always Visible and Larger */}
            {roleName && player.is_alive && (
               <div className={`
                 absolute left-1/2 top-full mt-14 -translate-x-1/2 px-3 py-1 rounded-full text-xs font-bold font-mono border shadow-md backdrop-blur-md tracking-[0.2em]
                 ${roleLabelClass}
               `}>
                 {roleName.toUpperCase()}
               </div>
            )}
          </motion.div>
        );
      })}
    </div>
  );
}

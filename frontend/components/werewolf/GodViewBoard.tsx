
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
  seatRadius?: number;
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


export default function GodViewBoard({ players, activeMessage, center, isAgent = true, seatRadius }: GodViewBoardProps) {
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
  const computedSeatRadius = hasSize ? Math.min(300, Math.max(180, minDim / 2 - 100)) : 280;
  const finalSeatRadius = typeof seatRadius === 'number' && Number.isFinite(seatRadius)
    ? seatRadius
    : computedSeatRadius;

  const ringColors = isAgent ? AGENT_RING_COLORS : HUMAN_RING_COLORS;
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
        const pos = getWerewolfSeatPosition(idx, players.length, finalSeatRadius);
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

        const seatNumber = idx + 1;
        const roleLabel = roleName ? roleName.toUpperCase() : 'PLAYER';
        const displayName = `${roleLabel} ${seatNumber}`;

        return (
          <motion.div
            key={player.sid}
            className="absolute w-20 h-20 z-20 pointer-events-auto"
            style={{ left, top, transform: 'translate(-50%, -50%)' }}
            initial={{ scale: 0 }}
            animate={{ scale: isSpeaking ? 1.1 : 1 }}
            transition={{ type: 'spring', stiffness: 300, damping: 20 }}
          >
            {/* Avatar Circle */}
            <AgentSummaryHover agentId={player.sid} agentName={player.nickname} isAgent={isAgent}>
              <div className={`
                w-full h-full rounded-full border-[4px] ${finalRingColor} ${finalBgColor}
                flex items-center justify-center relative
                ${isSpeaking ? 'ring-8 ring-yellow-400 ring-opacity-60 animate-pulse' : ''}
                transition-all duration-300
              `}>
                <div
                  className="absolute inset-2 rounded-full opacity-30"
                  style={{ background: `radial-gradient(circle at 30% 30%, hsl(${getPlayerHue(player.sid)} 85% 70%) 0%, transparent 60%)` }}
                />
                <span className="text-4xl filter drop-shadow-md select-none leading-none">{avatar}</span>

                {/* Seat Number */}
                <div className={`absolute -bottom-1 -right-1 w-7 h-7 rounded-full flex items-center justify-center border-2 text-xs font-bold shadow-lg ${
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
              title={displayName}
              className={`absolute left-1/2 bottom-full mb-1 -translate-x-1/2 text-[10px] uppercase tracking-[0.24em] text-center whitespace-nowrap ${
                isAgent ? 'text-emerald-200/80' : 'text-sky-700/80'
              }`}
            >
              {displayName}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}

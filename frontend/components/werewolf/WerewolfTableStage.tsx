'use client';

import React from 'react';
import GodViewBoard from '@/components/werewolf/GodViewBoard';
import InteractionGraph from '@/components/werewolf/InteractionGraph';
import type { WerewolfPlayer } from '@/store/types';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';

export const WEREWOLF_STAGE_WIDTH = 900;
export const WEREWOLF_STAGE_HEIGHT = 900;
// Tweak these to align player ring with the table center.
export const PLAYER_RING_CENTER_OFFSET = { x: -40, y: -20 };
export const PLAYER_RING_RADIUS_OFFSET = -10;

interface WerewolfTableStageProps {
  players: WerewolfPlayer[];
  votes: Record<string, string>;
  voteCounts?: Record<string, number>;
  activeMessage?: { sid: string; content: string };
  isAgent: boolean;
  tableSize: number;
  seatRadius: number;
  lineRadius: number;
}

export default function WerewolfTableStage({
  players,
  votes,
  voteCounts,
  activeMessage,
  isAgent,
  tableSize,
  seatRadius,
  lineRadius
}: WerewolfTableStageProps) {
  const baseCenter = React.useMemo(
    () => ({
      x: WEREWOLF_STAGE_WIDTH / 2,
      y: WEREWOLF_STAGE_HEIGHT / 2
    }),
    []
  );
  const tableCenter: AnchoredCenter = React.useMemo(
    () => ({
      percent: { left: '50%', top: '50%' },
      pixel: baseCenter,
      stageSize: { width: WEREWOLF_STAGE_WIDTH, height: WEREWOLF_STAGE_HEIGHT }
    }),
    [baseCenter]
  );
  const playerCenter: AnchoredCenter = React.useMemo(
    () => ({
      percent: { left: '50%', top: '50%' },
      pixel: {
        x: baseCenter.x + PLAYER_RING_CENTER_OFFSET.x,
        y: baseCenter.y + PLAYER_RING_CENTER_OFFSET.y
      },
      stageSize: { width: WEREWOLF_STAGE_WIDTH, height: WEREWOLF_STAGE_HEIGHT }
    }),
    [baseCenter]
  );
  const adjustedSeatRadius = seatRadius + PLAYER_RING_RADIUS_OFFSET;
  const adjustedLineRadius = lineRadius + PLAYER_RING_RADIUS_OFFSET;

  return (
    <div
      className="relative"
      style={{ width: WEREWOLF_STAGE_WIDTH, height: WEREWOLF_STAGE_HEIGHT }}
    >
      {/* Table Background */}
      <div
        className="absolute pointer-events-none z-0 select-none"
        style={{
          left: tableCenter.percent.left,
          top: tableCenter.percent.top,
          transform: 'translate(-50%, -50%)'
        }}
      >
        <div
          className="relative rounded-full"
          style={{
            width: `${tableSize}px`,
            height: `${tableSize}px`
          }}
        >
          <div className={`absolute inset-0 rounded-full border-[14px] box-border ${
            isAgent
              ? 'border-emerald-900/60 bg-[#0f1c14] shadow-[inset_0_0_120px_rgba(0,0,0,0.75)]'
              : 'border-sky-200/80 bg-sky-50/70 shadow-[inset_0_0_50px_rgba(14,165,233,0.08)]'
          }`}>
            <div
              className="absolute inset-0 rounded-full"
              style={{
                background: isAgent
                  ? 'radial-gradient(circle at center, rgba(16,185,129,0.18) 0%, rgba(16,185,129,0.08) 45%, rgba(0,0,0,0) 70%)'
                  : 'radial-gradient(circle at center, rgba(56,189,248,0.12) 0%, rgba(56,189,248,0.04) 45%, rgba(255,255,255,0) 70%)'
              }}
            />
            <div className={`absolute inset-5 rounded-full border ${isAgent ? 'border-emerald-500/25' : 'border-sky-200/70'}`} />
            <div className={`absolute inset-11 rounded-full border ${isAgent ? 'border-emerald-500/15' : 'border-sky-200/50'}`} />
          </div>

          {/* Center Info - Background Watermark */}
          <div className="absolute inset-0 flex items-center justify-center text-center pointer-events-none select-none">
            <div className={`text-[8rem] font-black tracking-tighter opacity-10 ${
              isAgent ? 'text-white' : 'text-slate-900'
            }`}>
              CLAW
            </div>
          </div>
        </div>
      </div>

      {/* Center Info - Lobster (True Center) */}
      <div className="absolute pointer-events-none z-10 select-none left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
        <div className="relative w-[10rem] h-[10rem] flex items-center justify-center">
          {isAgent && <div className="absolute inset-0 rounded-full bg-emerald-500/10 blur-2xl" />}
          <div
            className={`drop-shadow-[0_8px_24px_rgba(0,0,0,0.45)] leading-none opacity-85 ${
              isAgent ? 'text-[3rem]' : 'text-[3rem]'
            }`}
          >
            🦞
          </div>
        </div>
      </div>

      {/* Visualization */}
      <GodViewBoard
        players={players}
        activeMessage={activeMessage}
        center={playerCenter}
        isAgent={isAgent}
        seatRadius={adjustedSeatRadius}
      />
      <InteractionGraph
        players={players}
        center={playerCenter}
        isAgent={isAgent}
        seatRadius={adjustedSeatRadius}
        lineRadius={adjustedLineRadius}
        voteCounts={voteCounts}
      />
    </div>
  );
}

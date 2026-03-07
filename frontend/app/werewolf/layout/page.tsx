'use client';

import React from 'react';
import WerewolfTableStage, { WEREWOLF_STAGE_HEIGHT, WEREWOLF_STAGE_WIDTH } from '@/components/werewolf/WerewolfTableStage';
import type { WerewolfPlayer } from '@/store/types';
import { useUiMode } from '@/components/UiModeProvider';

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

export default function WerewolfLayoutPage() {
  const { readingMode } = useUiMode();
  const isAgent = readingMode === 'agent';
  const [playerCount, setPlayerCount] = React.useState(10);
  const [tableScale, setTableScale] = React.useState(0.72);
  const [seatInset, setSeatInset] = React.useState(44);
  const stageRef = React.useRef<HTMLDivElement | null>(null);
  const [stageSize, setStageSize] = React.useState({ width: 0, height: 0 });

  React.useEffect(() => {
    const node = stageRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const update = () => {
      const rect = node.getBoundingClientRect();
      setStageSize({ width: rect.width, height: rect.height });
    };
    const observer = new ResizeObserver(update);
    observer.observe(node);
    update();
    return () => observer.disconnect();
  }, []);

  const scale = Math.min(
    1,
    (stageSize.width || WEREWOLF_STAGE_WIDTH) / WEREWOLF_STAGE_WIDTH,
    (stageSize.height || WEREWOLF_STAGE_HEIGHT) / WEREWOLF_STAGE_HEIGHT
  );

  const safePlayerCount = clamp(Math.round(playerCount), 6, 12);
  const tableSize = Math.min(WEREWOLF_STAGE_WIDTH, WEREWOLF_STAGE_HEIGHT) * clamp(tableScale, 0.6, 0.9);
  const seatRadius = Math.max(120, tableSize / 2 - clamp(seatInset, 10, 120));
  const lineRadius = Math.max(100, seatRadius - 36);

  const players = React.useMemo<WerewolfPlayer[]>(() => {
    const list: WerewolfPlayer[] = [];
    for (let i = 0; i < safePlayerCount; i += 1) {
      list.push({
        sid: String(i + 1),
        nickname: `Agent ${i + 1}`,
        is_alive: true
      });
    }
    return list;
  }, [safePlayerCount]);

  return (
    <div className={`min-h-screen ${isAgent ? 'scanline-effect' : ''} font-mono`}>
      <div className="max-w-6xl mx-auto px-4 py-6">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
          <div>
            <div className={`text-xs uppercase tracking-[0.3em] ${isAgent ? 'text-emerald-300/70' : 'text-sky-600/70'}`}>
              Werewolf Layout
            </div>
            <div className={`text-2xl font-bold ${isAgent ? 'text-emerald-100' : 'text-sky-900'}`}>
              Seat Layout Preview
            </div>
          </div>
          <div className={`flex items-center gap-3 text-xs ${isAgent ? 'text-emerald-200/70' : 'text-sky-600/70'}`}>
            <span>Players</span>
            <input
              type="range"
              min={6}
              max={12}
              value={safePlayerCount}
              onChange={(e) => setPlayerCount(Number(e.target.value))}
            />
            <span>{safePlayerCount}</span>
          </div>
        </div>

        <div className={`grid gap-4 md:grid-cols-[220px_1fr]`}>
          <div className={`rounded-lg border p-4 space-y-4 ${
            isAgent ? 'border-emerald-500/20 bg-black/60 text-emerald-100' : 'border-sky-200/80 bg-sky-50/80 text-sky-800'
          }`}>
            <div className="text-[11px] uppercase tracking-[0.3em] opacity-70">Table</div>
            <div className="space-y-2">
              <label className="text-xs flex justify-between">
                <span>Table Scale</span>
                <span>{tableScale.toFixed(2)}</span>
              </label>
              <input
                type="range"
                min={0.6}
                max={0.9}
                step={0.01}
                value={tableScale}
                onChange={(e) => setTableScale(Number(e.target.value))}
                className="w-full"
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs flex justify-between">
                <span>Seat Inset</span>
                <span>{seatInset.toFixed(0)}px</span>
              </label>
              <input
                type="range"
                min={10}
                max={120}
                step={2}
                value={seatInset}
                onChange={(e) => setSeatInset(Number(e.target.value))}
                className="w-full"
              />
            </div>
            <div className={`text-[11px] ${isAgent ? 'text-emerald-200/70' : 'text-sky-600/70'}`}>
              Table: {Math.round(tableSize)}px · Seat Radius: {Math.round(seatRadius)}px
            </div>
          </div>

          <div
            ref={stageRef}
            className={`relative overflow-hidden rounded-xl border ${
              isAgent ? 'border-emerald-500/20 bg-black/60' : 'border-sky-200/80 bg-white'
            }`}
            style={{ minHeight: 640 }}
          >
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
              <div
                className="relative"
                style={{
                  width: WEREWOLF_STAGE_WIDTH,
                  height: WEREWOLF_STAGE_HEIGHT,
                  transform: `scale(${scale || 1})`,
                  transformOrigin: 'center center'
                }}
              >
                <WerewolfTableStage
                  players={players}
                  activeMessage={undefined}
                  isAgent={isAgent}
                  tableSize={tableSize}
                  seatRadius={seatRadius}
                  lineRadius={lineRadius}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

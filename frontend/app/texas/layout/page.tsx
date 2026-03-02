'use client';

import React from 'react';
import seatLayout from '@/config/texasSeatLayout.json';
import CommunityCards from '@/components/texas/CommunityCards';
import PlayerSeat, { SEAT_AVATARS } from '@/components/texas/PlayerSeat';
import type { SpectatorPlayer } from '@/store/types';
import type { AnchoredCenter } from '@/hooks/useAnchoredCenter';
import { getSeatSlotIndices, getSeatSlotPositions, TOTAL_SLOTS } from '@/components/texas/seatPositions';

type SlotOffsets = Record<number, { x: number; y: number }>;
type ElementOffsets = Record<'communityCards' | 'pot' | 'round' | 'winner' | 'actionPanel' | 'chatPanel', { x: number; y: number }>;

const BASE_STAGE_WIDTH = 1200;
const BASE_STAGE_HEIGHT = 820;
const TABLE_SHIFT_X = -12;
const ELEMENT_KEYS: Array<keyof ElementOffsets> = ['communityCards', 'pot', 'round', 'winner', 'actionPanel', 'chatPanel'];

const buildOffsets = (raw: any, fallback?: SlotOffsets): SlotOffsets => {
  const next: SlotOffsets = fallback ? { ...fallback } : {};
  for (let i = 0; i < TOTAL_SLOTS; i += 1) {
    if (!next[i]) next[i] = { x: 0, y: 0 };
  }
  if (!raw || typeof raw !== 'object') return next;
  Object.entries(raw).forEach(([key, value]) => {
    const idx = Number(key);
    const x = Number((value as any)?.x);
    const y = Number((value as any)?.y);
    if (!Number.isFinite(idx) || idx < 0 || idx >= TOTAL_SLOTS) return;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    next[idx] = { x, y };
  });
  return next;
};

const zeroOffsets = () => buildOffsets({});

const buildElementOffsets = (raw: any, fallback?: ElementOffsets): ElementOffsets => {
  const base: ElementOffsets = fallback
    ? { ...fallback }
    : {
      communityCards: { x: 0, y: 0 },
      pot: { x: 0, y: 0 },
      round: { x: 0, y: 0 },
      winner: { x: 0, y: 0 },
      actionPanel: { x: 0, y: 0 },
      chatPanel: { x: 0, y: 0 }
    };
  if (!raw || typeof raw !== 'object') return base;
  ELEMENT_KEYS.forEach((key) => {
    const value = raw[key];
    const x = Number((value as any)?.x);
    const y = Number((value as any)?.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    base[key] = { x, y };
  });
  return base;
};

const zeroElementOffsets = (): ElementOffsets => buildElementOffsets({});

export default function TexasLayoutEditorPage() {
  const [mounted, setMounted] = React.useState(false);
  const [playerCount, setPlayerCount] = React.useState(12);
  const [mirrorMode, setMirrorMode] = React.useState(true);
  const [status, setStatus] = React.useState<string | null>(null);
  const [slotOffsets, setSlotOffsets] = React.useState<SlotOffsets>(() => buildOffsets((seatLayout as any)?.slotOffsets));
  const [elementOffsets, setElementOffsets] = React.useState<ElementOffsets>(() =>
    buildElementOffsets((seatLayout as any)?.elementOffsets)
  );
  const stageRef = React.useRef<HTMLDivElement | null>(null);
  const [stageSize, setStageSize] = React.useState({ width: 0, height: 0 });
  const dragRef = React.useRef<{
    kind: 'slot' | 'element';
    index?: number;
    elementKey?: keyof ElementOffsets;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);

  React.useEffect(() => {
    setMounted(true);
  }, []);

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

  const updateDrag = React.useCallback((clientX: number, clientY: number) => {
    if (!dragRef.current) return;
    const { kind, index, elementKey, startX, startY, originX, originY } = dragRef.current;
    const scale = Math.min(
      1,
      (stageSize.width || BASE_STAGE_WIDTH) / BASE_STAGE_WIDTH,
      (stageSize.height || BASE_STAGE_HEIGHT) / BASE_STAGE_HEIGHT
    );
    const dx = (clientX - startX) / (scale || 1);
    const dy = (clientY - startY) / (scale || 1);
    if (kind === 'slot' && index !== undefined) {
      setSlotOffsets((prev) => {
        const next = { ...prev, [index]: { x: originX + dx, y: originY + dy } };
        if (mirrorMode) {
          const mirrorIndex = TOTAL_SLOTS - 1 - index;
          if (mirrorIndex !== index) {
            next[mirrorIndex] = { x: -(originX + dx), y: originY + dy };
          }
        }
        return next;
      });
    }
    if (kind === 'element' && elementKey) {
      setElementOffsets((prev) => ({
        ...prev,
        [elementKey]: { x: originX + dx, y: originY + dy }
      }));
    }
  }, [mirrorMode, stageSize.height, stageSize.width]);

  React.useEffect(() => {
    const onMove = (event: PointerEvent) => updateDrag(event.clientX, event.clientY);
    const onUp = () => {
      dragRef.current = null;
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [updateDrag]);

  const startElementDrag = (
    elementKey: keyof ElementOffsets,
    event: React.PointerEvent<HTMLElement>,
    originX: number,
    originY: number
  ) => {
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = {
      kind: 'element',
      elementKey,
      startX: event.clientX,
      startY: event.clientY,
      originX,
      originY
    };
  };

  const startSlotDrag = (index: number, event: React.PointerEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = {
      kind: 'slot',
      index,
      startX: event.clientX,
      startY: event.clientY,
      originX: slotOffsets[index]?.x ?? 0,
      originY: slotOffsets[index]?.y ?? 0
    };
  };

  const scale = Math.min(
    1,
    (stageSize.width || BASE_STAGE_WIDTH) / BASE_STAGE_WIDTH,
    (stageSize.height || BASE_STAGE_HEIGHT) / BASE_STAGE_HEIGHT
  );

  const baseSlots = React.useMemo(
    () => getSeatSlotPositions({ width: BASE_STAGE_WIDTH, height: BASE_STAGE_HEIGHT }, zeroOffsets()),
    []
  );
  const slotPositions = React.useMemo(
    () => getSeatSlotPositions({ width: BASE_STAGE_WIDTH, height: BASE_STAGE_HEIGHT }, slotOffsets),
    [slotOffsets]
  );
  const activeSlots = React.useMemo(
    () => new Set(getSeatSlotIndices(playerCount, slotPositions)),
    [playerCount, slotPositions]
  );
  const seatCenter: AnchoredCenter = React.useMemo(
    () => ({
      percent: { left: '50%', top: '50%' },
      pixel: { x: BASE_STAGE_WIDTH / 2, y: BASE_STAGE_HEIGHT / 2 },
      stageSize: { width: BASE_STAGE_WIDTH, height: BASE_STAGE_HEIGHT }
    }),
    []
  );
  const dummyPlayers = React.useMemo(() => {
    const ranks = ['A', 'K', 'Q', 'J', '10', '9', '8', '7', '6', '5', '4', '3', '2'];
    const suits = ['s', 'h', 'd', 'c'];
    return Array.from({ length: TOTAL_SLOTS }, (_, idx) => {
      const rank1 = ranks[idx % ranks.length];
      const suit1 = suits[idx % suits.length];
      const rank2 = ranks[(idx + 5) % ranks.length];
      const suit2 = suits[(idx + 2) % suits.length];
      return {
        sid: `seat_${idx}`,
        nickname: `Seat ${idx + 1}`,
        chips: 1000,
        status: 'active',
        hole_cards: [`${rank1}${suit1}`, `${rank2}${suit2}`],
        current_bet: 0
      } as SpectatorPlayer;
    });
  }, []);

  const exportJson = () => {
    const payload = { slotOffsets, elementOffsets };
    const text = JSON.stringify(payload, null, 2);
    navigator.clipboard?.writeText(text).catch(() => {});
    setStatus('JSON copied to clipboard');
  };

  const exportTs = () => {
    const entries = Object.keys(slotOffsets)
      .sort((a, b) => Number(a) - Number(b))
      .map((key) => {
        const value = slotOffsets[Number(key)];
        return `  ${key}: { x: ${value.x}, y: ${value.y} }`;
      });
    const text = `const SLOT_OFFSETS = {\n${entries.join(',\n')}\n};`;
    navigator.clipboard?.writeText(text).catch(() => {});
    setStatus('TS snippet copied to clipboard');
  };

  const resetToZero = () => {
    setSlotOffsets(zeroOffsets());
    setStatus('Offsets cleared');
  };

  const resetElements = () => {
    setElementOffsets(zeroElementOffsets());
    setStatus('Elements cleared');
  };

  const centerToTable = () => {
    const base = getSeatSlotPositions({ width: BASE_STAGE_WIDTH, height: BASE_STAGE_HEIGHT }, zeroOffsets());
    const averageX = base.reduce((sum, pos, idx) => sum + pos.x + (slotOffsets[idx]?.x ?? 0), 0) / TOTAL_SLOTS;
    setSlotOffsets((prev) => {
      const next: SlotOffsets = { ...prev };
      for (let i = 0; i < TOTAL_SLOTS; i += 1) {
        const current = next[i] || { x: 0, y: 0 };
        next[i] = { x: current.x - averageX, y: current.y };
      }
      return next;
    });
    setStatus('Centered to table');
  };

  const mirrorAll = () => {
    setSlotOffsets((prev) => {
      const next: SlotOffsets = { ...prev };
      for (let i = 0; i < TOTAL_SLOTS; i += 1) {
        const mirrorIndex = TOTAL_SLOTS - 1 - i;
        if (mirrorIndex === i) continue;
        const source = prev[i] || { x: 0, y: 0 };
        next[mirrorIndex] = { x: -source.x, y: source.y };
      }
      return next;
    });
    setStatus('Mirrored all slots');
  };

  const reloadFromFile = async () => {
    try {
      const res = await fetch('/api/texas-seat-layout');
      const data = await res.json();
      setSlotOffsets(buildOffsets(data?.slotOffsets));
      setElementOffsets(buildElementOffsets(data?.elementOffsets));
      setStatus('Reloaded from file');
    } catch {
      setStatus('Reload failed');
    }
  };

  const saveToFile = async () => {
    try {
      const res = await fetch('/api/texas-seat-layout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slotOffsets, elementOffsets })
      });
      if (!res.ok) throw new Error('save failed');
      setStatus('Saved to config file');
    } catch {
      setStatus('Save failed');
    }
  };

  if (!mounted) {
    return (
      <div className="min-h-screen w-full bg-black text-emerald-100 font-mono flex items-center justify-center">
        <div className="text-xs tracking-widest opacity-70">Loading layout editor…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen w-full bg-black text-emerald-100 font-mono flex flex-col">
      <div className="max-w-6xl mx-auto px-6 py-6">
        <div className="flex flex-wrap items-center gap-4 justify-between">
          <div>
            <div className="text-xl font-bold tracking-wide">Texas Seat Layout Editor</div>
            <div className="text-xs opacity-70">拖拽座位调整偏移，保存后会写入配置文件。</div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={exportJson}
              className="px-3 py-1.5 rounded-full text-xs font-bold border border-emerald-400/40 bg-black/70 hover:border-emerald-300/70"
            >
              Copy JSON
            </button>
            <button
              type="button"
              onClick={exportTs}
              className="px-3 py-1.5 rounded-full text-xs font-bold border border-emerald-400/40 bg-black/70 hover:border-emerald-300/70"
            >
              Copy TS
            </button>
            <button
              type="button"
              onClick={reloadFromFile}
              className="px-3 py-1.5 rounded-full text-xs font-bold border border-emerald-400/40 bg-black/70 hover:border-emerald-300/70"
            >
              Reload
            </button>
            <button
              type="button"
              onClick={saveToFile}
              className="px-3 py-1.5 rounded-full text-xs font-bold border border-emerald-300 bg-emerald-500/20 hover:bg-emerald-500/30"
            >
              Save
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs uppercase tracking-widest opacity-80">
            Players
            <input
              type="range"
              min={2}
              max={12}
              value={playerCount}
              onChange={(event) => setPlayerCount(Number(event.target.value))}
            />
            <span className="text-sm font-bold">{playerCount}</span>
          </label>
          <label className="flex items-center gap-2 text-xs uppercase tracking-widest opacity-80">
            Mirror
            <input
              type="checkbox"
              checked={mirrorMode}
              onChange={(event) => setMirrorMode(event.target.checked)}
            />
          </label>
          <button
            type="button"
            onClick={resetToZero}
            className="px-3 py-1.5 rounded-full text-xs font-bold border border-rose-400/40 bg-black/70 hover:border-rose-300/70"
          >
            Clear Offsets
          </button>
          <button
            type="button"
            onClick={resetElements}
            className="px-3 py-1.5 rounded-full text-xs font-bold border border-rose-400/40 bg-black/70 hover:border-rose-300/70"
          >
            Clear Elements
          </button>
          <button
            type="button"
            onClick={centerToTable}
            className="px-3 py-1.5 rounded-full text-xs font-bold border border-emerald-400/40 bg-black/70 hover:border-emerald-300/70"
          >
            Center X
          </button>
          <button
            type="button"
            onClick={mirrorAll}
            className="px-3 py-1.5 rounded-full text-xs font-bold border border-emerald-400/40 bg-black/70 hover:border-emerald-300/70"
          >
            Mirror All
          </button>
          {status && <div className="text-xs text-emerald-300">{status}</div>}
        </div>
      </div>

      <div ref={stageRef} className="relative w-full flex-1 min-h-[640px] overflow-hidden pb-10 bg-black">
        <div
          className="absolute left-0 top-0 bottom-0 w-80 border-r px-4 py-4 overflow-x-hidden bg-black/60 text-emerald-100 border-emerald-500/20"
          style={{ transform: `translate(${elementOffsets.actionPanel.x}px, ${elementOffsets.actionPanel.y}px)` }}
          onPointerDown={(event) =>
            startElementDrag('actionPanel', event, elementOffsets.actionPanel.x, elementOffsets.actionPanel.y)
          }
        >
          <div className="text-[13px] font-bold uppercase tracking-[0.32em] opacity-80">Actions</div>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex items-start gap-2 text-emerald-200/70">
              <span className="text-base">🚀</span>
              <span>Seat 3 raise 12</span>
            </div>
            <div className="flex items-start gap-2 text-emerald-200/70">
              <span className="text-base">✅</span>
              <span>Seat 6 check</span>
            </div>
            <div className="flex items-start gap-2 text-emerald-200/70">
              <span className="text-base">💥</span>
              <span>Seat 9 all-in</span>
            </div>
          </div>
        </div>
        <div
          className="absolute right-0 top-0 bottom-0 w-80 border-l px-4 py-4 overflow-x-hidden bg-black/60 text-emerald-100 border-emerald-500/20"
          style={{ transform: `translate(${elementOffsets.chatPanel.x}px, ${elementOffsets.chatPanel.y}px)` }}
          onPointerDown={(event) =>
            startElementDrag('chatPanel', event, elementOffsets.chatPanel.x, elementOffsets.chatPanel.y)
          }
        >
          <div className="text-[13px] font-bold uppercase tracking-[0.32em] opacity-80">Chat</div>
          <div className="mt-3 space-y-2 text-sm">
            <div>Seat 1: nice hand</div>
            <div>Seat 4: thinking...</div>
            <div>Seat 8: ok</div>
          </div>
        </div>
        <div
          className="absolute left-1/2 top-1/2"
          style={{
            left: `calc(50% + ${TABLE_SHIFT_X}px)`,
            width: BASE_STAGE_WIDTH,
            height: BASE_STAGE_HEIGHT,
            transform: `translate(-50%, -50%) scale(${scale})`,
            transformOrigin: 'center center'
          }}
        >
          <div className="absolute left-1/2 top-0 bottom-0 w-px bg-emerald-400/30" />
          <div className="absolute top-1/2 left-0 right-0 h-px bg-emerald-400/20" />
          <div className="absolute inset-4 m-auto w-[82%] h-[72%] border-[18px] rounded-[220px] shadow-2xl relative border-[#1a1a1a] bg-[#0f2a15] shadow-[inset_0_0_100px_rgba(0,0,0,0.8)]">
            <div
              className="absolute left-1/2 top-1.5 z-30 pointer-events-auto"
              style={{
                transform: `translate(-50%, 0) translate(${elementOffsets.round.x}px, ${elementOffsets.round.y}px)`
              }}
              onPointerDown={(event) => startElementDrag('round', event, elementOffsets.round.x, elementOffsets.round.y)}
            >
              <div className="px-5 py-2 rounded-full text-sm font-bold tracking-wide border bg-black/70 border-emerald-400/40 text-emerald-100">
                Round 1: PREFLOP
              </div>
            </div>
            <div
              className="absolute left-1/2 top-12 z-40 pointer-events-auto"
              style={{
                transform: `translate(-50%, 0) translate(${elementOffsets.winner.x}px, ${elementOffsets.winner.y}px)`
              }}
              onPointerDown={(event) => startElementDrag('winner', event, elementOffsets.winner.x, elementOffsets.winner.y)}
            >
              <div className="px-6 py-2 rounded-full border text-sm font-bold tracking-wide bg-amber-500/15 border-amber-300/60 text-amber-100 shadow-[0_0_24px_rgba(251,191,36,0.45)]">
                WINNER: Seat 1 +120
              </div>
            </div>
            <CommunityCards
              cards={['As', 'Kh', 'Qd', 'Jc', '10s']}
              offset={elementOffsets.communityCards}
              onPointerDown={(event) =>
                startElementDrag('communityCards', event, elementOffsets.communityCards.x, elementOffsets.communityCards.y)
              }
            />
            <div
              className="absolute left-1/2 top-[12%] z-40"
              style={{
                width: 520,
                height: 150,
                transform: `translate(-50%, 0) translate(${elementOffsets.communityCards.x}px, ${elementOffsets.communityCards.y}px)`,
                cursor: 'grab',
                pointerEvents: 'auto',
                background: 'rgba(0,0,0,0.001)',
                touchAction: 'none',
                userSelect: 'none'
              }}
              onPointerDown={(event) =>
                startElementDrag('communityCards', event, elementOffsets.communityCards.x, elementOffsets.communityCards.y)
              }
            />
            <div
              className="absolute left-1/2 top-1/2 z-30 pointer-events-auto"
              style={{
                transform: `translate(-50%, -50%) translate(${elementOffsets.pot.x}px, ${elementOffsets.pot.y}px)`
              }}
              onPointerDown={(event) => startElementDrag('pot', event, elementOffsets.pot.x, elementOffsets.pot.y)}
            >
              <div className="px-5 py-2 rounded-full border text-sm font-bold tracking-wide bg-black/75 border-emerald-400/40 text-emerald-100 shadow-[0_10px_30px_rgba(16,185,129,0.2)]">
                POT 🪙120
              </div>
            </div>
          </div>

          {baseSlots.map((base, idx) => {
            const pos = slotPositions[idx];
            const active = activeSlots.has(idx);
            return (
              <React.Fragment key={`slot-${idx}`}>
                <div
                  className={`absolute flex items-center justify-center w-8 h-8 rounded-full border text-[10px] font-bold ${
                    active ? 'bg-emerald-500/15 border-emerald-300 text-emerald-100' : 'bg-black/40 border-emerald-800/40 text-emerald-500/50'
                  }`}
                  style={{
                    left: `${BASE_STAGE_WIDTH / 2 + pos.x}px`,
                    top: `${BASE_STAGE_HEIGHT / 2 + pos.y}px`,
                    transform: 'translate(-50%, -50%)'
                  }}
                >
                  {idx}
                </div>
                {active && (
                  <PlayerSeat
                    player={dummyPlayers[idx]}
                    index={idx}
                    totalPlayers={playerCount}
                    center={seatCenter}
                    positionOverride={pos}
                    avatarOverride={SEAT_AVATARS[idx % SEAT_AVATARS.length]}
                    isAgent
                    onPointerDown={(event) => startSlotDrag(idx, event)}
                  />
                )}
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </div>
  );
}

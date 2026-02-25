import seatLayout from '@/config/texasSeatLayout.json';

interface SeatStageSize {
  width: number;
  height: number;
}

export const TOTAL_SLOTS = 12;

const DEFAULT_SLOT_OFFSETS: Record<number, { x: number; y: number }> = {
  0: { x: -47.322265625, y: -115.666015625 },
  1: { x: -1.8828125, y: -113.427734375 },
  2: { x: 32.654296875, y: -9.486328125 },
  3: { x: 64.1328125, y: 3.609375 },
  4: { x: 69.30078125, y: -3.7734375 },
  5: { x: 13.412109375, y: 0.361328125 },
  6: { x: -13.412109375, y: 0.361328125 },
  7: { x: -69.30078125, y: -3.7734375 },
  8: { x: -64.1328125, y: 3.609375 },
  9: { x: -32.654296875, y: -9.486328125 },
  10: { x: 1.8828125, y: -113.427734375 },
  11: { x: 47.322265625, y: -115.666015625 }
};

const coerceSlotOffsets = (raw: any, fallback: Record<number, { x: number; y: number }>) => {
  const result: Record<number, { x: number; y: number }> = { ...fallback };
  if (!raw || typeof raw !== 'object') return result;
  Object.entries(raw).forEach(([key, value]) => {
    const idx = Number(key);
    const x = Number((value as any)?.x);
    const y = Number((value as any)?.y);
    if (!Number.isFinite(idx) || !Number.isFinite(x) || !Number.isFinite(y)) return;
    result[idx] = { x, y };
  });
  return result;
};

const SLOT_OFFSETS = coerceSlotOffsets((seatLayout as any)?.slotOffsets, DEFAULT_SLOT_OFFSETS);

const buildBaseSlots = (stageSize?: SeatStageSize) => {
  const width = stageSize?.width || 1200;
  const height = stageSize?.height || 800;

  const slotCount = TOTAL_SLOTS;

  // Dynamic radii based on stage size to avoid crowding on small screens
  const baseRadiusX = Math.min(620, Math.max(280, width * 0.44));
  const seatWidth = 176; // matches PlayerSeat width (w-44)
  const minRadiusForSpacing = slotCount > 1 ? (seatWidth * slotCount) / (Math.PI * 2) : baseRadiusX;
  const radiusX = Math.min(Math.max(baseRadiusX, minRadiusForSpacing), width * 0.56);
  const radiusY = Math.min(340, Math.max(190, height * 0.28, radiusX * 0.58));
  const yOffset = height * 0.04;

  // Distribute seats around left/right/bottom only, keep top clear for board.
  const arcStart = Math.PI * 0.02;  // ~4° (farther right)
  const arcEnd = Math.PI * 0.98;    // ~176° (farther left)
  const arc = arcEnd - arcStart;

  return Array.from({ length: TOTAL_SLOTS }, (_, slotIndex) => {
    const t = TOTAL_SLOTS <= 1 ? 0.5 : slotIndex / (TOTAL_SLOTS - 1);
    const angle = arcStart + t * arc;
    return {
      x: radiusX * Math.cos(angle),
      y: radiusY * Math.sin(angle) + yOffset
    };
  });
};

export const getSeatSlotPositions = (stageSize?: SeatStageSize, overrides?: Record<number, { x: number; y: number }>) => {
  const baseSlots = buildBaseSlots(stageSize);
  const offsets = overrides ?? SLOT_OFFSETS;
  return baseSlots.map((base, slotIndex) => {
    const offset = offsets[slotIndex];
    if (!offset) return base;
    return { x: base.x + offset.x, y: base.y + offset.y };
  });
};

export const getSeatSlotIndices = (totalPlayers: number, slotPositions: Array<{ x: number; y: number }>) => {
  let slotIndices = Array.from({ length: TOTAL_SLOTS }, (_, slotIndex) => slotIndex);
  if (totalPlayers < TOTAL_SLOTS) {
    const toRemove = TOTAL_SLOTS - totalPlayers;
    const pairs: Array<[number, number]> = [];
    for (let i = 0; i < TOTAL_SLOTS / 2; i += 1) {
      pairs.push([i, TOTAL_SLOTS - 1 - i]);
    }
    const orderedPairs = pairs
      .map((pair) => {
        const [a, b] = pair;
        const avgY = (slotPositions[a].y + slotPositions[b].y) / 2;
        return { pair, avgY };
      })
      .sort((a, b) => a.avgY - b.avgY);

    const removalOrder: number[] = [];
    orderedPairs.forEach(({ pair }) => {
      const [a, b] = pair;
      const right = slotPositions[a].x >= slotPositions[b].x ? a : b;
      const left = right === a ? b : a;
      removalOrder.push(right, left);
    });

    const removeSet = new Set<number>(removalOrder.slice(0, toRemove));
    slotIndices = slotIndices.filter((slotIndex) => !removeSet.has(slotIndex));
  }
  return slotIndices;
};

export const getSeatPosition = (index: number, totalPlayers: number, stageSize?: SeatStageSize) => {
  // Use elliptical distribution to match the poker table shape
  if (totalPlayers === 0) return { x: 0, y: 0 };

  const slotPositions = getSeatSlotPositions(stageSize);
  const slotIndices = getSeatSlotIndices(totalPlayers, slotPositions);
  const slotIndex = slotIndices[Math.min(index, slotIndices.length - 1)] ?? 0;
  return slotPositions[slotIndex] ?? { x: 0, y: 0 };
};

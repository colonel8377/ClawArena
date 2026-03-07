import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

export const runtime = 'nodejs';

const TOTAL_SLOTS = 12;

const resolveConfigPath = async () => {
  const cwd = process.cwd();
  const direct = path.join(cwd, 'config', 'texasSeatLayout.json');
  try {
    await fs.access(direct);
    return direct;
  } catch {
  }
  const fallback = path.join(cwd, 'frontend', 'config', 'texasSeatLayout.json');
  return fallback;
};

interface SeatOffset {
  x: number;
  y: number;
}

interface SeatOffsets {
  [key: string]: SeatOffset;
}

const normalizeOffsets = (raw: SeatOffsets | null | undefined, fallback: SeatOffsets) => {
  const result: SeatOffsets = { ...fallback };
  if (!raw || typeof raw !== 'object') return result;
  Object.entries(raw).forEach(([key, value]) => {
    const idx = Number(key);
    const x = Number(value?.x);
    const y = Number(value?.y);
    if (!Number.isFinite(idx) || idx < 0 || idx >= TOTAL_SLOTS) return;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    result[String(idx)] = { x, y };
  });
  return result;
};

const normalizeElementOffsets = (raw: Record<string, { x: number; y: number }> | null | undefined, fallback: Record<string, { x: number; y: number }>) => {
  const keys = ['communityCards', 'pot', 'round', 'winner', 'actionPanel', 'chatPanel'];
  const result: Record<string, { x: number; y: number }> = { ...fallback };
  keys.forEach((key) => {
    const value = raw?.[key];
    const x = Number(value?.x);
    const y = Number(value?.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    result[key] = { x, y };
  });
  return result;
};

export async function GET() {
  const configPath = await resolveConfigPath();
  try {
    const raw = await fs.readFile(configPath, 'utf-8');
    return NextResponse.json(JSON.parse(raw));
  } catch {
    return NextResponse.json({ error: 'layout_not_found' }, { status: 404 });
  }
}

export async function POST(request: Request) {
  const configPath = await resolveConfigPath();
  const payload = await request.json();

  let current: { slotOffsets?: SeatOffsets; elementOffsets?: Record<string, { x: number; y: number }> } = {};
  try {
    const raw = await fs.readFile(configPath, 'utf-8');
    current = JSON.parse(raw);
  } catch {
  }

  const existingOffsets = current?.slotOffsets || {};
  const normalized = normalizeOffsets(payload?.slotOffsets, existingOffsets);
  const existingElements = current?.elementOffsets || {};
  const normalizedElements = normalizeElementOffsets(payload?.elementOffsets, existingElements);

  const next = {
    slotOffsets: normalized,
    elementOffsets: normalizedElements,
    updatedAt: new Date().toISOString()
  };

  await fs.writeFile(configPath, JSON.stringify(next, null, 2) + '\n', 'utf-8');
  return NextResponse.json(next);
}

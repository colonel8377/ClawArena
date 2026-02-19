import getApiBaseUrl from '@/lib/api';
import { botFetch } from '@/lib/antiBot';

export type ActiveRoom = {
  room_id: number | string;
  game_id?: number | string | null;
  game_type?: number | null;
  phase?: string | null;
  room_state?: number | null;
  members_count?: number;
  spectators_count?: number;
};

export type RoomChatMessage = {
  id: string;
  room_id: number;
  game_id?: number;
  game_type?: number;
  channel: string;
  sender_id?: number | null;
  sender_name?: string | null;
  content: string;
  ts_ms: number;
};

export type RoomChatHistory = {
  items: RoomChatMessage[];
  last_id?: string | null;
};

export const fetchActiveRooms = async (limit = 50): Promise<ActiveRoom[]> => {
  const apiBase = getApiBaseUrl();
  const res = await botFetch(`${apiBase}/api/rooms/active?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`rooms.active failed (${res.status})`);
  }
  const payload = (await res.json()) as { ok?: boolean; data?: { items?: ActiveRoom[] }; message?: string };
  if (!payload.ok) {
    throw new Error(payload.message || 'rooms.active failed');
  }
  return payload.data?.items || [];
};

export const fetchRoomChatHistory = async (
  roomId: number | string,
  limit = 50,
  beforeId?: string,
  afterId?: string
): Promise<RoomChatHistory> => {
  const apiBase = getApiBaseUrl();
  const params = new URLSearchParams({ limit: String(limit) });
  if (beforeId) params.set('before_id', beforeId);
  if (afterId) params.set('after_id', afterId);
  const res = await botFetch(`${apiBase}/api/rooms/${roomId}/chat?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`rooms.chat failed (${res.status})`);
  }
  const payload = (await res.json()) as { ok?: boolean; data?: RoomChatHistory; message?: string };
  if (!payload.ok) {
    throw new Error(payload.message || 'rooms.chat failed');
  }
  return payload.data || { items: [] };
};

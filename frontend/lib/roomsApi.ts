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
  event_id?: string | null;
  action_id?: string | null;
  hand_index?: number | null;
  phase?: string | null;
};

export type RoomChatHistory = {
  items: RoomChatMessage[];
  last_id?: string | null;
};

export type RoomEvent = {
  id: string;
  event_id: string;
  event_type: string;
  ts_ms: number;
  room_id: number;
  game_id?: number;
  actor_id?: number | null;
  action_id?: string | null;
  cause_id?: string | null;
  payload: Record<string, unknown>;
};

export type RoomEventHistory = {
  items: RoomEvent[];
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
  afterId?: string,
  handIndex?: number
): Promise<RoomChatHistory> => {
  const apiBase = getApiBaseUrl();
  const params = new URLSearchParams({ limit: String(limit) });
  if (beforeId) params.set('before_id', beforeId);
  if (afterId) params.set('after_id', afterId);
  if (handIndex !== undefined && handIndex !== null) params.set('hand_index', String(handIndex));
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

export const fetchRoomEventHistory = async (
  roomId: number | string,
  limit = 50,
  beforeId?: string,
  afterId?: string,
  types?: string[],
  includeChat?: boolean
): Promise<RoomEventHistory> => {
  const apiBase = getApiBaseUrl();
  const params = new URLSearchParams({ limit: String(limit) });
  if (beforeId) params.set('before_id', beforeId);
  if (afterId) params.set('after_id', afterId);
  if (types && types.length > 0) params.set('types', types.join(','));
  if (includeChat) params.set('include_chat', 'true');
  const res = await botFetch(`${apiBase}/api/rooms/${roomId}/events?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`rooms.events failed (${res.status})`);
  }
  const payload = (await res.json()) as { ok?: boolean; data?: RoomEventHistory; message?: string };
  if (!payload.ok) {
    throw new Error(payload.message || 'rooms.events failed');
  }
  return payload.data || { items: [] };
};

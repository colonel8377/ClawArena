import getApiBaseUrl from '@/lib/api';
import { botFetch } from '@/lib/antiBot';

export type AgentHistorySummary = {
  agent_id: number;
  agent_name: string;
  win_rate: number;
  wins: number;
  losses: number;
  games_played: number;
  recent: Array<{
    game_type: number;
    result: number;
    room_id: number;
    ended_at?: string | null;
  }>;
};

export const fetchAgentSummary = async (agentId: number | string): Promise<AgentHistorySummary> => {
  const apiBase = getApiBaseUrl();
  const res = await botFetch(`${apiBase}/api/history/summary?agent_id=${agentId}`);
  if (!res.ok) {
    throw new Error(`history.summary failed (${res.status})`);
  }
  const payload = (await res.json()) as { ok?: boolean; data?: AgentHistorySummary; message?: string };
  if (!payload.ok) {
    throw new Error(payload.message || 'history.summary failed');
  }
  if (!payload.data) {
    throw new Error('history.summary missing data');
  }
  return payload.data;
};

'use client';

import React from 'react';
import { fetchAgentSummary, AgentHistorySummary } from '@/lib/historyApi';

const CACHE_TTL_MS = 15000;
const summaryCache = new Map<number, { data: AgentHistorySummary; ts: number }>();
const inflight = new Map<number, Promise<AgentHistorySummary>>();

const getCached = (agentId: number): AgentHistorySummary | null => {
  const cached = summaryCache.get(agentId);
  if (!cached) return null;
  if (Date.now() - cached.ts > CACHE_TTL_MS) {
    summaryCache.delete(agentId);
    return null;
  }
  return cached.data;
};

const setCached = (agentId: number, data: AgentHistorySummary) => {
  summaryCache.set(agentId, { data, ts: Date.now() });
};

const mapGameType = (value: number) => (value === 1 ? 'WW' : value === 2 ? 'TX' : 'UNK');
const mapResult = (value: number) => (value === 1 ? 'W' : value === 2 ? 'L' : value === 3 ? 'E' : '-');

type AgentSummaryHoverProps = {
  agentId?: string | number;
  agentName?: string;
  isAgent?: boolean;
  children: React.ReactNode;
};

export default function AgentSummaryHover({
  agentId,
  agentName,
  isAgent = true,
  children,
}: AgentSummaryHoverProps) {
  const numericId = Number(agentId);
  const canFetch = Number.isFinite(numericId) && numericId > 0;
  const [summary, setSummary] = React.useState<AgentHistorySummary | null>(null);
  const [status, setStatus] = React.useState<'idle' | 'loading' | 'ready' | 'error'>('idle');

  const loadSummary = React.useCallback(async () => {
    if (!canFetch || status === 'loading' || status === 'ready') {
      return;
    }
    const cached = getCached(numericId);
    if (cached) {
      setSummary(cached);
      setStatus('ready');
      return;
    }
    setStatus('loading');
    let pending = inflight.get(numericId);
    if (!pending) {
      pending = fetchAgentSummary(numericId);
      inflight.set(numericId, pending);
    }
    try {
      const data = await pending;
      setCached(numericId, data);
      setSummary(data);
      setStatus('ready');
    } catch {
      setStatus('error');
    } finally {
      inflight.delete(numericId);
    }
  }, [canFetch, numericId, status]);

  const winRatePct = summary ? Math.round(summary.win_rate * 100) : 0;
  const recentLabel = summary?.recent?.length
    ? summary.recent
        .map((item) => `${mapGameType(item.game_type)} ${mapResult(item.result)}`)
        .join(' · ')
    : 'No recent games';

  return (
    <div className="relative group" onMouseEnter={loadSummary}>
      {children}
      {canFetch && (
        <div
          className={`absolute left-1/2 top-full mt-3 -translate-x-1/2 whitespace-nowrap pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-150 z-40 ${
            isAgent ? 'text-purple-100' : 'text-slate-700'
          }`}
        >
          <div
            className={`px-3 py-2 rounded-lg border shadow-lg text-xs backdrop-blur-md ${
              isAgent
                ? 'bg-black/90 border-purple-500/40'
                : 'bg-white/95 border-slate-200'
            }`}
          >
            <div className="font-semibold">
              {agentName || `agent_${numericId}`}
            </div>
            {status === 'loading' && <div className="opacity-70">Loading stats...</div>}
            {status === 'error' && <div className="opacity-70">Stats unavailable</div>}
            {status === 'ready' && summary && (
              <>
                <div className="opacity-80 mt-1">
                  Win rate: {winRatePct}% ({summary.wins}-{summary.losses})
                </div>
                <div className="opacity-80 mt-1">Recent: {recentLabel}</div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

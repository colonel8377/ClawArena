'use client';

import { useEffect, useState } from 'react';
import { getSocket } from '@/lib/socket';
import getApiBaseUrl, { getApiHost, getAppEnvLabel } from '@/lib/api';
import { botFetch } from '@/lib/antiBot';

type HealthResponse = {
  status: string;
  active_tables: number;
  local_debug_mode: boolean;
};

export default function BackendStatus() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [socketConnected, setSocketConnected] = useState<boolean>(false);
  const appEnvLabel = getAppEnvLabel();
  const apiHost = getApiHost();

  const appEnvClassName =
    appEnvLabel === 'DEV'
      ? 'status-inactive'
      : appEnvLabel === 'PRE'
        ? 'text-warning'
        : 'status-active';

  useEffect(() => {
    let mounted = true;
    const API_URL = getApiBaseUrl();

    botFetch(`${API_URL}/health`)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const data = (await res.json()) as HealthResponse;
        if (mounted) {
          setHealth(data);
          setError(null);
        }
      })
      .catch((err: Error) => {
        if (mounted) setError(err.message);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    const socket = getSocket();
    if (!socket) return;

    const onConnect = () => setSocketConnected(true);
    const onDisconnect = () => setSocketConnected(false);

    setSocketConnected(socket.connected);

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
    };
  }, []);

  const apiStatusLabel = loading
    ? 'POLLING...'
    : error
      ? 'UNREACHABLE'
      : health?.status?.toUpperCase() ?? 'UNKNOWN';

  return (
    <div className="terminal-border neon-glow-blue relative digital-noise">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm text-cyberBlue font-orbitron text-shadow-neon-blue">
          &gt; BACKEND STATUS
        </h3>
        <span className={`text-xs ${socketConnected ? 'status-active' : 'status-inactive'}`}>
          SOCKET {socketConnected ? 'ONLINE' : 'OFFLINE'}
        </span>
      </div>
      <div className="text-xs font-mono space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-foreground opacity-70">API</span>
          <span className={error ? 'text-danger' : 'text-acidGreen'}>{apiStatusLabel}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-foreground opacity-70">
            Tables: <span className="text-cyberBlue">{health?.active_tables ?? '-'}</span>
          </span>
          <span className="text-foreground opacity-70">
            Env: <span className={appEnvClassName}>{appEnvLabel}</span>
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-foreground opacity-70">API Host</span>
          <span className="text-cyberBlue">{apiHost}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-foreground opacity-70">Backend Debug</span>
          <span className={health?.local_debug_mode ? 'status-inactive' : 'status-active'}>
            {health?.local_debug_mode ? 'ON' : 'OFF'}
          </span>
        </div>
        {error && (
          <div className="text-danger opacity-70">
            Error: {error}
          </div>
        )}
      </div>
    </div>
  );
}

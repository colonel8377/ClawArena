'use client';

import { useEffect, useState } from 'react';
import { getSocket } from '@/lib/socket';
import getApiBaseUrl from '@/lib/api';

type HealthResponse = {
  status: string;
  active_tables: number;
  web3_connected: boolean;
  local_debug_mode: boolean;
};

export default function BackendStatus() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [socketConnected, setSocketConnected] = useState<boolean>(false);

  useEffect(() => {
    let mounted = true;
    const API_URL = getApiBaseUrl();

    fetch(`${API_URL}/health`)
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
        <div className="grid grid-cols-2 gap-2">
          <div className="text-foreground opacity-70">
            Tables: <span className="text-cyberBlue">{health?.active_tables ?? '-'}</span>
          </div>
          <div className="text-foreground opacity-70">
            Web3:{' '}
            <span className={health?.web3_connected ? 'status-active' : 'status-inactive'}>
              {health?.web3_connected ? 'CONNECTED' : 'OFFLINE'}
            </span>
          </div>
        </div>
        <div className="text-foreground opacity-70">
          Mode:{' '}
          <span className="text-neonPink">
            {health?.local_debug_mode ? 'DEBUG' : 'SECURE'}
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

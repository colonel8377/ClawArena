'use client';

import { useEffect, useState } from 'react';
import getApiBaseUrl from '@/lib/api';
import {
  clearBotGate,
  hasValidToken,
  initBotReady,
  isGateActive,
  markBotReady,
  onGateChange,
  requestToken,
  setBotToken,
} from '@/lib/antiBot';
import { getStoredFingerprint } from '@/lib/antiBot';
import { refreshSocketAuth } from '@/lib/socket';

type GateState = 'idle' | 'checking' | 'ready' | 'error';

export default function AntiBotGate() {
  const [active, setActive] = useState<boolean>(isGateActive());
  const [state, setState] = useState<GateState>('idle');
  const [error, setError] = useState<string>('');
  const [retryTick, setRetryTick] = useState<number>(0);

  useEffect(() => {
    initBotReady();
    const cleanup = onGateChange(setActive);
    return () => { cleanup(); };
  }, []);

  useEffect(() => {
    if (!active) {
      setState('idle');
      setError('');
      return;
    }
    const run = async () => {
      setState('checking');
      if (hasValidToken() && getStoredFingerprint()) {
        markBotReady();
        refreshSocketAuth();
        clearBotGate();
        setState('ready');
        return;
      }
      try {
        const apiBase = getApiBaseUrl();
        const response = await requestToken(apiBase);
        setBotToken(response.token);
        markBotReady();
        refreshSocketAuth(response.token);
        clearBotGate();
        setState('ready');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Token request failed');
        setState('error');
      }
    };
    run();
  }, [active, retryTick]);

  if (!active || state === 'ready' || state === 'idle') {
    return null;
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 w-full max-w-xs">
      <div className="terminal-border neon-glow-purple bg-backgroundSlate/90 p-4 space-y-3">
        <div className="text-electricPurple font-orbitron text-lg">&gt; Bot Protection</div>
        {state === 'checking' && <div className="text-sm text-foreground/70">Initializing...</div>}
        {state === 'error' && (
          <>
            <div className="text-sm text-danger">Failed: {error}</div>
            <button
              onClick={() => setRetryTick((value) => value + 1)}
              className="w-full px-3 py-2 bg-danger/20 border border-danger/60 rounded text-sm text-danger hover:bg-danger/30 transition-colors"
            >
              Retry
            </button>
          </>
        )}
      </div>
    </div>
  );
}

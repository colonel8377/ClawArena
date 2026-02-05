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
  requestChallenge,
  setBotToken,
  submitChallenge,
} from '@/lib/antiBot';
import { getStoredFingerprint } from '@/lib/antiBot';
import { refreshSocketAuth } from '@/lib/socket';

type GateState = 'idle' | 'checking' | 'challenge' | 'verifying' | 'ready' | 'error';

export default function AntiBotGate() {
  const [active, setActive] = useState<boolean>(isGateActive());
  const [state, setState] = useState<GateState>('idle');
  const [question, setQuestion] = useState<string>('');
  const [answer, setAnswer] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [challengeId, setChallengeId] = useState<string>('');
  const [powDifficulty, setPowDifficulty] = useState<number>(0);
  const [powSalt, setPowSalt] = useState<string>('');
  const [retryTick, setRetryTick] = useState<number>(0);

  useEffect(() => {
    initBotReady();
    return onGateChange(setActive);
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
        const challenge = await requestChallenge(apiBase);
        setQuestion(challenge.question);
        setChallengeId(challenge.challenge_id);
        setPowSalt(challenge.pow_salt);
        setPowDifficulty(challenge.pow_difficulty);
        setState('challenge');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Challenge failed');
        setState('error');
      }
    };
    run();
  }, [active, retryTick]);

  const handleVerify = async () => {
    setError('');
    setState('verifying');
    try {
      const apiBase = getApiBaseUrl();
      const response = await submitChallenge(
        apiBase,
        {
          challenge_id: challengeId,
          question,
          pow_salt: powSalt,
          pow_difficulty: powDifficulty,
          expires_in: 0,
          risk: 0,
        },
        answer
      );
      setBotToken(response.bot_token);
      markBotReady();
      refreshSocketAuth(response.bot_token);
      clearBotGate();
      setState('ready');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verify failed');
      setState('error');
    }
  };

  if (!active || state === 'ready' || state === 'idle') {
    return null;
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 w-full max-w-xs">
      <div className="terminal-border neon-glow-purple bg-backgroundSlate/90 p-4 space-y-3">
        <div className="text-electricPurple font-orbitron text-lg">&gt; Bot Protection</div>
        {state === 'checking' && <div className="text-sm text-foreground/70">Initializing...</div>}
        {state === 'challenge' && (
          <>
            <div className="text-sm text-foreground/80">
              Please solve the challenge to continue.
            </div>
            <div className="text-acidGreen font-mono text-base">{question}</div>
            <input
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Answer"
              className="w-full px-3 py-2 bg-background border border-electricPurple/40 rounded text-sm text-foreground focus:border-electricPurple focus:outline-none"
            />
            <button
              onClick={handleVerify}
              className="w-full px-3 py-2 bg-electricPurple/20 border border-electricPurple/60 rounded text-sm text-electricPurple hover:bg-electricPurple/30 transition-colors"
            >
              Verify
            </button>
          </>
        )}
        {state === 'verifying' && (
          <div className="text-sm text-foreground/70">Verifying proof of work...</div>
        )}
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

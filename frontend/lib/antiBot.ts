type BotChallenge = {
  challenge_id: string;
  question: string;
  pow_salt: string;
  pow_difficulty: number;
  expires_in: number;
  risk: number;
};

type BotVerifyResponse = {
  bot_token: string;
  expires_in: number;
  risk: number;
};

const BOT_TOKEN_KEY = 'aga-bot-token';
const BOT_FP_KEY = 'aga-bot-fp';

let readyPromise: Promise<void> | null = null;
let readyResolve: (() => void) | null = null;
let gateActive = false;
const gateListeners = new Set<(active: boolean) => void>();

export const initBotReady = () => {
  if (!readyPromise) {
    readyPromise = new Promise((resolve) => {
      readyResolve = resolve;
    });
  }
};

export const markBotReady = () => {
  readyResolve?.();
};

export const waitForBotReady = async () => {
  initBotReady();
  if (readyPromise) {
    await readyPromise;
  }
};

export const requestBotGate = () => {
  if (!gateActive) {
    gateActive = true;
    initBotReady();
    gateListeners.forEach((cb) => cb(true));
  }
};

export const clearBotGate = () => {
  if (gateActive) {
    gateActive = false;
    gateListeners.forEach((cb) => cb(false));
  }
};

export const isGateActive = () => gateActive;

export const onGateChange = (cb: (active: boolean) => void) => {
  gateListeners.add(cb);
  return () => gateListeners.delete(cb);
};

const sha256Hex = async (value: string): Promise<string> => {
  const encoder = new TextEncoder();
  const data = encoder.encode(value);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
};

const sha256Bytes = async (value: string): Promise<Uint8Array> => {
  const encoder = new TextEncoder();
  const data = encoder.encode(value);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return new Uint8Array(digest);
};

const hasLeadingZeroBits = (hash: Uint8Array, difficulty: number): boolean => {
  let bits = difficulty;
  for (const byte of hash) {
    if (bits <= 0) return true;
    if (bits >= 8) {
      if (byte !== 0) return false;
      bits -= 8;
      continue;
    }
    const mask = (0xff << (8 - bits)) & 0xff;
    return (byte & mask) === 0;
  }
  return bits <= 0;
};

export const getFingerprint = async (): Promise<string> => {
  if (typeof window === 'undefined') return 'server';
  const cached = window.localStorage.getItem(BOT_FP_KEY);
  if (cached) return cached;

  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  if (ctx) {
    ctx.textBaseline = 'top';
    ctx.font = "14px 'Arial'";
    ctx.fillStyle = '#f60';
    ctx.fillRect(125, 1, 62, 20);
    ctx.fillStyle = '#069';
    ctx.fillText('agent-arena', 2, 15);
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
    ctx.fillText('agent-arena', 4, 17);
  }

  const gl = canvas.getContext('webgl');
  let glInfo = '';
  if (gl) {
    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info') as WebGLDebugRendererInfo | null;
    const vendor = debugInfo ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
    const renderer = debugInfo ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    glInfo = `${vendor}::${renderer}`;
  }

  const payload = {
    ua: navigator.userAgent,
    lang: navigator.language,
    langs: navigator.languages,
    platform: navigator.platform,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    screen: [screen.width, screen.height, screen.colorDepth, devicePixelRatio],
    memory: (navigator as Navigator & { deviceMemory?: number }).deviceMemory || 0,
    cores: navigator.hardwareConcurrency || 0,
    canvas: canvas.toDataURL(),
    webgl: glInfo,
  };

  const fp = await sha256Hex(JSON.stringify(payload));
  window.localStorage.setItem(BOT_FP_KEY, fp);
  return fp;
};

export const getStoredFingerprint = (): string | null => {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(BOT_FP_KEY);
};

export const getBotToken = (): string | null => {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(BOT_TOKEN_KEY);
};

export const setBotToken = (token: string) => {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(BOT_TOKEN_KEY, token);
};

const getTokenExpiry = (token: string): number => {
  const parts = token.split('.');
  if (parts.length < 2) return 0;
  try {
    const json = atob(parts[0].replace(/-/g, '+').replace(/_/g, '/'));
    const payload = JSON.parse(json) as { exp?: number };
    return payload.exp || 0;
  } catch {
    return 0;
  }
};

export const hasValidToken = (): boolean => {
  const token = getBotToken();
  if (!token) return false;
  return getTokenExpiry(token) > Math.floor(Date.now() / 1000) + 30;
};

export const computePowNonce = async (salt: string, difficulty: number): Promise<string> => {
  let nonce = 0;
  while (true) {
    const hash = await sha256Bytes(`${salt}:${nonce}`);
    if (hasLeadingZeroBits(hash, difficulty)) {
      return String(nonce);
    }
    nonce += 1;
    if (nonce % 400 === 0) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
  }
};

export const getBotHeaders = async (): Promise<Record<string, string>> => {
  const fingerprint = await getFingerprint();
  const token = getBotToken();
  return {
    'X-Fingerprint': fingerprint,
    ...(token ? { 'X-Bot-Token': token } : {}),
  };
};

export const botFetch = async (url: string, init?: RequestInit): Promise<Response> => {
  const headers = await getBotHeaders();
  const mergedHeaders = {
    ...(init?.headers || {}),
    ...headers,
  };
  const res = await fetch(url, { ...init, headers: mergedHeaders });
  if (res.status !== 403 && res.status !== 429) {
    return res;
  }
  try {
    const data = (await res.clone().json()) as {
      error?: string;
      code?: string;
      challenge_required?: boolean;
    };
    if (data?.error === 'bot_protection' && data.challenge_required) {
      requestBotGate();
      await waitForBotReady();
      const retryHeaders = await getBotHeaders();
      return fetch(url, { ...init, headers: { ...(init?.headers || {}), ...retryHeaders } });
    }
  } catch {
    // ignore parse failures
  }
  return res;
};

export const requestChallenge = async (apiBase: string): Promise<BotChallenge> => {
  const fingerprint = await getFingerprint();
  const res = await fetch(`${apiBase}/bot/challenge`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Fingerprint': fingerprint,
    },
    body: JSON.stringify({ fingerprint }),
  });
  if (!res.ok) {
    throw new Error(`Challenge failed (${res.status})`);
  }
  return (await res.json()) as BotChallenge;
};

export const submitChallenge = async (
  apiBase: string,
  challenge: BotChallenge,
  answer: string
): Promise<BotVerifyResponse> => {
  const fingerprint = await getFingerprint();
  const powNonce = await computePowNonce(challenge.pow_salt, challenge.pow_difficulty);
  const res = await fetch(`${apiBase}/bot/verify`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Fingerprint': fingerprint,
    },
    body: JSON.stringify({
      challenge_id: challenge.challenge_id,
      answer,
      pow_nonce: powNonce,
      fingerprint,
    }),
  });
  if (!res.ok) {
    throw new Error(`Verify failed (${res.status})`);
  }
  return (await res.json()) as BotVerifyResponse;
};

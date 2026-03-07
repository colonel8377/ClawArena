interface WebGLDebugRendererInfo {
  readonly UNMASKED_VENDOR_WEBGL: number;
  readonly UNMASKED_RENDERER_WEBGL: number;
}

type BotTokenResponse = {
  token: string;
  expires_in: number;
  agent_id?: number;
  agent_name?: string;
  reward_granted?: boolean;
  reward_amount?: number;
  message?: string;
  error?: string;
};

const BOT_TOKEN_KEY = 'aga-bot-token';
const BOT_TOKEN_EXP_KEY = 'aga-bot-token-exp';
const BOT_FP_KEY = 'aga-bot-fp';
const PLAYER_ID_KEY = 'aga-player-id';
const LOGIN_SECRET_KEY = 'aga-login-secret';
const AGENT_NAME_KEY = 'aga-agent-name';

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

export const setBotToken = (token: string, expiresIn?: number) => {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(BOT_TOKEN_KEY, token);
  if (expiresIn && expiresIn > 0) {
    window.localStorage.setItem(BOT_TOKEN_EXP_KEY, String(Date.now() + expiresIn * 1000));
  }
};

const getEnvPlayerId = (): string | null => {
  const value = process.env.NEXT_PUBLIC_AGENT_ID?.trim() || process.env.NEXT_PUBLIC_AGENT_PLAYER_ID?.trim();
  return value && value.length > 0 ? value : null;
};

const getEnvLoginSecret = (): string | null => {
  const value = process.env.NEXT_PUBLIC_AGENT_SECRET?.trim() || process.env.NEXT_PUBLIC_AGENT_LOGIN_SECRET?.trim();
  return value && value.length > 0 ? value : null;
};

const getEnvAgentName = (): string | null => {
  const value = process.env.NEXT_PUBLIC_AGENT_NAME?.trim();
  return value && value.length > 0 ? value : null;
};

export const getStoredPlayerId = (): string | null => {
  if (typeof window === 'undefined') {
    return getEnvPlayerId();
  }
  return window.localStorage.getItem(PLAYER_ID_KEY) || getEnvPlayerId();
};

export const getStoredLoginSecret = (): string | null => {
  if (typeof window === 'undefined') {
    return getEnvLoginSecret();
  }
  return window.localStorage.getItem(LOGIN_SECRET_KEY) || getEnvLoginSecret();
};

export const getStoredAgentName = (): string | null => {
  if (typeof window === 'undefined') {
    return getEnvAgentName();
  }
  return window.localStorage.getItem(AGENT_NAME_KEY) || getEnvAgentName();
};

export const setAgentCredentials = (playerId: string, loginSecret: string) => {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(PLAYER_ID_KEY, playerId);
  window.localStorage.setItem(LOGIN_SECRET_KEY, loginSecret);
};

export const setAgentName = (agentName: string) => {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(AGENT_NAME_KEY, agentName);
};

export const clearAgentCredentials = () => {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(PLAYER_ID_KEY);
  window.localStorage.removeItem(LOGIN_SECRET_KEY);
  window.localStorage.removeItem(AGENT_NAME_KEY);
};

export const hasValidToken = (): boolean => {
  const token = getBotToken();
  if (!token) return false;
  if (typeof window === 'undefined') return true;
  const rawExpiry = window.localStorage.getItem(BOT_TOKEN_EXP_KEY);
  if (!rawExpiry) return false;
  const expiryMs = Number(rawExpiry);
  if (!Number.isFinite(expiryMs)) return true;
  return expiryMs > Date.now() + 30 * 1000;
};

export const getBotHeaders = async (): Promise<Record<string, string>> => {
  const token = getBotToken();
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
};

export const botFetch = async (url: string, init?: RequestInit): Promise<Response> => {
  const headers = await getBotHeaders();
  const mergedHeaders = {
    ...(init?.headers || {}),
    ...headers,
  };
  const res = await fetch(url, { ...init, headers: mergedHeaders });
  if (res.status !== 401 && res.status !== 403 && res.status !== 429) {
    return res;
  }
  const hasCredentials = !!(getStoredPlayerId() && getStoredLoginSecret());
  if (hasCredentials) {
    requestBotGate();
    await waitForBotReady();
    const retryHeaders = await getBotHeaders();
    return fetch(url, { ...init, headers: { ...(init?.headers || {}), ...retryHeaders } });
  }
  return res;
};

export const requestToken = async (apiBase: string): Promise<BotTokenResponse> => {
  const player_id = getStoredPlayerId();
  const login_secret = getStoredLoginSecret();

  if (!player_id || !login_secret) {
    throw new Error('Agent credentials missing. Set agent_id and secret before requesting a token.');
  }

  const res = await fetch(`${apiBase}/api/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ agent_id: Number(player_id), secret: login_secret }),
  });
  if (!res.ok) {
    throw new Error(`Token request failed (${res.status})`);
  }
  const payload = (await res.json()) as { ok?: boolean; data?: BotTokenResponse; message?: string };
  if (!payload.ok || !payload.data?.token) {
    throw new Error(payload.message || 'Token response missing token');
  }
  if (payload.data.agent_name) {
    setAgentName(payload.data.agent_name);
  }
  return payload.data;
};

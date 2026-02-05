const defaultBase = 'https://arena.openclaw.io';

export const getApiBaseUrl = (): string => {
  const envBase = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (envBase) return envBase.replace(/\/$/, '');

  if (typeof window !== 'undefined') {
    const { protocol, hostname } = window.location;
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return `${protocol}//${hostname}:8000`;
    }
  }

  return defaultBase;
};

export default getApiBaseUrl;

const defaultBase = 'https://api.clawarena.io';

export type AppEnv = 'dev' | 'pre' | 'prod';

const normalizeAppEnv = (value?: string): AppEnv | null => {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (normalized === 'development' || normalized === 'dev') return 'dev';
  if (normalized === 'preview' || normalized === 'pre') return 'pre';
  if (normalized === 'production' || normalized === 'prod') return 'prod';
  return null;
};

const normalizeApiBase = (value: string): string => {
  // Check if it already has a scheme
  if (/^https?:\/\//i.test(value)) {
    return value.replace(/\/$/, '');
  }

  // Default to http for localhost, https otherwise
  const scheme = (value.includes('localhost') || value.includes('127.0.0.1')) 
    ? 'http' 
    : 'https';
    
  const withScheme = `${scheme}://${value}`;

  try {
    const url = new URL(withScheme);
    if (url.hostname === 'www.clawarena.io') {
      const match = url.pathname.match(/^\/(api(?:-dev|-pre)?\.clawarena\.io)\/?$/);
      if (match) {
        return `https://${match[1]}`;
      }
    }
  } catch {
    return withScheme.replace(/\/$/, '');
  }

  return withScheme.replace(/\/$/, '');
};

export const getApiBaseUrl = (): string => {
  const envBase = process.env.NEXT_PUBLIC_API_URL?.trim();
  const base = envBase && envBase.length > 0 ? envBase : defaultBase;
  return normalizeApiBase(base);
};

export const getAppEnv = (): AppEnv => {
  const explicitEnv = normalizeAppEnv(process.env.NEXT_PUBLIC_APP_ENV);
  if (explicitEnv) return explicitEnv;

  const apiBase = getApiBaseUrl();
  if (apiBase.includes('api-dev.clawarena.io')) return 'dev';
  if (apiBase.includes('api-pre.clawarena.io')) return 'pre';

  if (process.env.NODE_ENV === 'development') return 'dev';
  return 'prod';
};

export const getAppEnvLabel = (): string => getAppEnv().toUpperCase();

export const getApiHost = (): string => {
  try {
    return new URL(getApiBaseUrl()).host;
  } catch {
    return getApiBaseUrl();
  }
};

export default getApiBaseUrl;

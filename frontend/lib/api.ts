const defaultBase = 'https://arena.openclaw.io';

export const getApiBaseUrl = (): string => {
  const envBase = process.env.NEXT_PUBLIC_API_URL;

  if (typeof window !== 'undefined') {
    const base = envBase && envBase.trim().length > 0 ? envBase : window.location.origin;
    return base.replace(/\/$/, '');
  }

  return (envBase || defaultBase).replace(/\/$/, '');
};

export default getApiBaseUrl;

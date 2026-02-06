const defaultBase = 'https://api.clawarena.io';

export const getApiBaseUrl = (): string => {
  const envBase = process.env.NEXT_PUBLIC_API_URL;
  const base = envBase && envBase.trim().length > 0 ? envBase : defaultBase;
  return base.replace(/\/$/, '');
};

export default getApiBaseUrl;

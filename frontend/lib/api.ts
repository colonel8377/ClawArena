const defaultBase = 'https://api.clawarena.io';

export const getApiBaseUrl = (): string => {
  const envBase = process.env.NEXT_PUBLIC_API_URL?.trim();
  const base = envBase && envBase.length > 0 ? envBase : defaultBase;
  return base.replace(/\/$/, '');
};

export default getApiBaseUrl;

'use client';
 
 import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
 
 type ReadingMode = 'human' | 'agent';
type ThemeMode = 'system' | 'light' | 'dark';
 
 type UiModeContextValue = {
   readingMode: ReadingMode;
   setReadingMode: (mode: ReadingMode) => void;
  themeMode: ThemeMode;
  setThemeMode: (mode: ThemeMode) => void;
 };
 
 const UiModeContext = createContext<UiModeContextValue | undefined>(undefined);
 
const READING_MODE_KEY = 'aga-reading-mode';
const THEME_MODE_KEY = 'aga-theme-mode';
 
 const isReadingMode = (value: string | null): value is ReadingMode =>
   value === 'human' || value === 'agent';
 
const isThemeMode = (value: string | null): value is ThemeMode =>
  value === 'system' || value === 'light' || value === 'dark';

const applyTheme = (media: MediaQueryList, root: HTMLElement, mode: ThemeMode) => {
  if (mode === 'system') {
    root.dataset.theme = media.matches ? 'light' : 'dark';
    return;
  }
  root.dataset.theme = mode;
};
 
 export function UiModeProvider({ children }: { children: React.ReactNode }) {
  const [readingMode, setReadingModeState] = useState<ReadingMode>('human');
  const [themeMode, setThemeModeState] = useState<ThemeMode>('system');
 
   useEffect(() => {
     const stored = window.localStorage.getItem(READING_MODE_KEY);
     if (isReadingMode(stored)) {
       setReadingModeState(stored);
     }
    const storedTheme = window.localStorage.getItem(THEME_MODE_KEY);
    if (isThemeMode(storedTheme)) {
      setThemeModeState(storedTheme);
    }
   }, []);
 
   useEffect(() => {
     window.localStorage.setItem(READING_MODE_KEY, readingMode);
     document.documentElement.dataset.reading = readingMode;
   }, [readingMode]);
 
   useEffect(() => {
     const root = document.documentElement;
     const media = window.matchMedia('(prefers-color-scheme: light)');
    const handler = () => applyTheme(media, root, themeMode);

    window.localStorage.setItem(THEME_MODE_KEY, themeMode);
    handler();

    if (themeMode === 'system') {
      if (media.addEventListener) {
        media.addEventListener('change', handler);
      } else {
        media.addListener(handler);
      }

      return () => {
        if (media.removeEventListener) {
          media.removeEventListener('change', handler);
        } else {
          media.removeListener(handler);
        }
      };
    }

    return;
  }, [themeMode]);
 
   const value = useMemo(
     () => ({
       readingMode,
       setReadingMode: setReadingModeState,
      themeMode,
      setThemeMode: setThemeModeState,
     }),
    [readingMode, themeMode]
   );
 
   return <UiModeContext.Provider value={value}>{children}</UiModeContext.Provider>;
 }
 
 export function useUiMode() {
   const context = useContext(UiModeContext);
   if (!context) {
     throw new Error('useUiMode must be used within UiModeProvider');
   }
   return context;
 }

import { create } from 'zustand';
import { TexasGameState } from './types';

interface TexasStore {
  gameState: TexasGameState | null;
  isConnected: boolean;
  revealMode: boolean;
  gameLog: string[];
  
  // Actions
  setGameState: (state: TexasGameState) => void;
  setConnected: (connected: boolean) => void;
  setRevealMode: (reveal: boolean) => void;
  addLog: (log: string) => void;
  clearLog: () => void;
  reset: () => void;
}

export const useTexasStore = create<TexasStore>((set) => ({
  gameState: null,
  isConnected: false,
  revealMode: false,
  gameLog: [],

  setGameState: (state) => set({ gameState: state }),
  setConnected: (connected) => set({ isConnected: connected }),
  setRevealMode: (reveal) => set({ revealMode: reveal }),
  addLog: (log) => set((state) => ({ gameLog: [...state.gameLog.slice(-49), log] })),
  clearLog: () => set({ gameLog: [] }),
  reset: () => set({ gameState: null, isConnected: false, gameLog: [] }),
}));

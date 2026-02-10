import { create } from 'zustand';
import { WerewolfGameState, ActionTrace } from './types';

interface WerewolfStore {
  gameState: WerewolfGameState | null;
  isConnected: boolean;
  revealMode: boolean;
  actionTimeline: ActionTrace[];
  
  // Actions
  setGameState: (state: WerewolfGameState) => void;
  setConnected: (connected: boolean) => void;
  setRevealMode: (reveal: boolean) => void;
  addAction: (action: ActionTrace) => void;
  reset: () => void;
}

export const useWerewolfStore = create<WerewolfStore>((set) => ({
  gameState: null,
  isConnected: false,
  revealMode: false,
  actionTimeline: [],

  setGameState: (state) => set({ gameState: state }),
  setConnected: (connected) => set({ isConnected: connected }),
  setRevealMode: (reveal) => set({ revealMode: reveal }),
  addAction: (action) => set((state) => ({ 
    actionTimeline: [action, ...state.actionTimeline].slice(0, 50) 
  })),
  reset: () => set({ gameState: null, isConnected: false, actionTimeline: [] }),
}));

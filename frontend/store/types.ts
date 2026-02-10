export interface SpectatorPlayer {
  sid: string;
  nickname: string;
  chips: number;
  status: string; // 'active' | 'folded' | 'allin' | 'sitout'
  cards?: string[]; // Exposed cards (if any)
  hole_cards?: string[]; // Only visible in Reveal Mode or Showdown
  current_bet?: number;
  last_action?: string;
  wallet_address?: string;
}

export interface TexasGameState {
  game_id: string;
  phase: string; // 'preflop' | 'flop' | 'turn' | 'river' | 'showdown'
  pot: number;
  current_bet: number;
  community_cards: string[];
  players: SpectatorPlayer[];
  dealer_position?: number;
  current_player?: string; // SID of current actor
  small_blind?: number;
  big_blind?: number;
  chat_history?: ChatMessage[];
  hand_number?: number;
  winners?: string[];
}

export interface WerewolfPlayer {
  sid: string;
  nickname: string;
  role?: string | { name: string; type: string }; // Role info
  is_alive: boolean;
  voted_for?: string; // SID of target
  wallet_address?: string;
}

export interface WerewolfGameState {
  game_id: string;
  phase: string; // 'night' | 'day_discussion' | 'day_voting' | 'finished'
  day_count: number;
  players: WerewolfPlayer[];
  last_action?: string;
  eliminated_last_night?: string;
  votes?: Record<string, string>; // voter_sid -> target_sid
  chat_messages?: ChatMessage[];
  wolf_chat?: ChatMessage[];
  current_speaker?: string;
  time_remaining?: number;
  winners?: string[];
}

export interface ChatMessage {
  nickname: string;
  message: string;
  action?: string;
  timestamp?: string;
  phase?: string;
  is_wolf_chat?: boolean;
}

export interface ActionTrace {
  game_id: string;
  phase: string;
  actor_sid?: string;
  actor_nickname?: string;
  action: string;
  message?: string;
  target?: { sid?: string; nickname?: string } | null;
  timestamp?: string;
}

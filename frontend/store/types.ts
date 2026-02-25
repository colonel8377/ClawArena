export interface SpectatorPlayer {
  sid: string;
  nickname: string;
  chips: number;
  status: string; // 'active' | 'folded' | 'allin' | 'sitout' | 'out' | 'busted'
  cards?: string[]; // Exposed cards (if any)
  hole_cards?: string[]; // Only visible in Reveal Mode or Showdown
  current_bet?: number;
  last_action?: string;
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
  hand_actions?: Array<{ action_type: number; actor_id?: number; amount?: number; phase?: string }>;
  winners?: string[];
  timers?: Record<string, number>;
}

export interface WerewolfPlayer {
  sid: string;
  nickname: string;
  role?: string | { role: string; team: string; description?: string }; // Role info from backend get_role_info()
  is_alive: boolean;
  status?: string;
  is_zombie?: boolean;
  voted_for?: string; // SID of target
}

export interface WerewolfGameState {
  game_id: string;
  phase: string; // 'night' | 'day_discussion' | 'day_voting' | 'finished'
  day_count: number;
  players: WerewolfPlayer[];
  last_action?: string;
  eliminated_last_night?: string[];
  votes?: Record<string, string>; // voter_sid -> target_sid
  vote_counts?: Record<string, number>; // target_sid -> count
  eliminated?: string[];
  phase_reason?: string;
  phase_forced?: boolean;
  offline_deaths?: string[];
  chat_messages?: ChatMessage[];
  wolf_chat?: ChatMessage[];
  current_speaker?: string;
  time_remaining?: number;
  winners?: string[];
  deaths?: Array<{ sid: string; nickname: string; cause: string; role_revealed?: string }>;
  timers?: Record<string, number>;
}

export interface ChatMessage {
  id?: string;
  sid?: string;
  nickname: string;
  message: string;
  action?: string;
  timestamp?: string;
  ts_ms?: number;
  phase?: string;
  is_wolf_chat?: boolean;
  isSystem?: boolean;
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

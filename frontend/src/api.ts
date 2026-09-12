function apiBase(): string {
  // Override esplicito (es. produzione)
  if (import.meta.env.VITE_API_BASE) return import.meta.env.VITE_API_BASE;
  // Dev: path relativo → proxy Vite /api → backend (funziona da PC e cellulare)
  if (import.meta.env.DEV) return "";
  const host = typeof window !== "undefined" ? window.location.hostname : "127.0.0.1";
  return `http://${host}:8000`;
}

const API_BASE = apiBase();

export type SessionSummary = {
  session_id: string;
  story_id: string;
  story_name: string;
  player_name: string;
  location: string;
  time: string;
  updated_at: string;
  active?: boolean;
};

export type StorySummary = {
  id: string;
  name: string;
  description: string;
  start_location: string;
  default_front?: string | null;
  has_wiki: boolean;
};

export type PlayableCharacter = {
  id: string;
  name: string;
  summary: string;
};

export type RaceOption = {
  id: string;
  name: string;
};

export type FrontOption = {
  id: string;
  name: string;
};

export type GameState = {
  session_id: string;
  story_id?: string;
  day?: number;
  minutes?: number;
  time: string;
  player: {
    id: string;
    name: string;
    location: string;
    party_id?: string | null;
    character_id?: string;
    origin?: "lore" | "custom";
    race?: string | null;
  };
  characters_active: string[];
  situations: Array<string | { id: string; summary: string }>;
  party_active?: string | null;
  fronts?: Record<string, unknown>;
  turns_since_present_review: number;
  turns_since_consolidation: number;
};

export type AppConfig = {
  present_review_every_n: number;
  consolidate_every_n: number;
};

export type SessionCreatePayload = {
  player_name: string;
  story_id: string;
  origin: "lore" | "custom";
  character_id?: string | null;
  race?: string | null;
  details?: string;
  start_mode: "arc" | "free";
  front_id?: string | null;
  start_location?: string | null;
};

export async function getConfig(): Promise<AppConfig> {
  const res = await fetch(`${API_BASE}/api/config`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listStories(): Promise<StorySummary[]> {
  const res = await fetch(`${API_BASE}/api/stories`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listPlayable(storyId: string): Promise<PlayableCharacter[]> {
  const res = await fetch(`${API_BASE}/api/stories/${storyId}/playable`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getPlayableSheet(
  storyId: string,
  characterId: string,
): Promise<CharacterSheet> {
  const res = await fetch(`${API_BASE}/api/stories/${storyId}/playable/${characterId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listRaces(storyId: string): Promise<RaceOption[]> {
  const res = await fetch(`${API_BASE}/api/stories/${storyId}/races`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listFronts(storyId: string): Promise<FrontOption[]> {
  const res = await fetch(`${API_BASE}/api/stories/${storyId}/fronts`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listSessions(): Promise<SessionSummary[]> {
  const res = await fetch(`${API_BASE}/api/saves`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/session/${sessionId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
}

export async function createSession(
  payload: SessionCreatePayload,
): Promise<{ session_id: string; state: GameState }> {
  const res = await fetch(`${API_BASE}/api/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function sendChat(sessionId: string, message: string) {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{
    reply: string;
    state: GameState;
    present_review_ran: boolean;
    consolidation_ran: boolean;
    turns_until_present_review: number;
    turns_until_consolidation: number;
    input_tokens: number;
    input_tokens_system: number;
    input_tokens_user: number;
    input_tokens_cached: number;
    review_tokens: number;
    can_undo: boolean;
    undo_count: number;
  }>;
}

export async function undoLastTurn(sessionId: string): Promise<{
  session_id: string;
  state: GameState;
  messages: { role: "user" | "assistant"; content: string }[];
  can_undo: boolean;
  undo_count: number;
}> {
  const res = await fetch(`${API_BASE}/api/session/${sessionId}/undo-last-turn`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getCanUndo(
  sessionId: string,
): Promise<{ can_undo: boolean; undo_count: number }> {
  const res = await fetch(`${API_BASE}/api/session/${sessionId}/can-undo`);
  if (!res.ok) throw new Error(await res.text());
  const data = (await res.json()) as { can_undo: boolean; undo_count?: number };
  return {
    can_undo: Boolean(data.can_undo),
    undo_count: Number(data.undo_count ?? 0),
  };
}

export async function getState(sessionId: string): Promise<GameState> {
  const res = await fetch(`${API_BASE}/api/state/${sessionId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getChat(sessionId: string): Promise<{ role: "user" | "assistant"; content: string }[]> {
  const res = await fetch(`${API_BASE}/api/chat/${sessionId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export type SpellEntry = {
  name: string;
  description: string;
};

export type CharacterSheet = {
  id: string;
  name: string;
  role?: string | null;
  location?: string | null;
  race?: string | null;
  job?: string | null;
  affiliation?: string | null;
  residence?: string | null;
  level?: string | number | null;
  body: string;
  spells?: SpellEntry[];
};

export type Spellbook = {
  player_id: string;
  spells: SpellEntry[];
};

export async function getPlayerSheet(sessionId: string): Promise<CharacterSheet> {
  const res = await fetch(`${API_BASE}/api/session/${sessionId}/sheet?t=${Date.now()}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getSpellbook(sessionId: string): Promise<Spellbook> {
  const res = await fetch(`${API_BASE}/api/session/${sessionId}/spellbook?t=${Date.now()}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export type ArcTimelineBeat = {
  id: string;
  title: string;
  place: string;
  status: "done" | "current" | "upcoming" | "skipped";
  summary?: string;
  hours_after_previous?: number;
  estimated_day?: number | null;
  due_time?: string | null;
};

export type ArcTimelineFront = {
  id: string;
  name: string;
  status: string;
  cursor_beat?: string | null;
  last_fired_beat?: string | null;
  beats: ArcTimelineBeat[];
};

export type ArcTimeline = {
  fronts: ArcTimelineFront[];
};

export async function getArcTimeline(sessionId: string): Promise<ArcTimeline> {
  const res = await fetch(`${API_BASE}/api/session/${sessionId}/arc-timeline?t=${Date.now()}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

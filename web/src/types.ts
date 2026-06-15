// ─── OpenAI messages ────────────────────────────────────────
export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

// ─── Entrance result types (V3 only) ────────────────────────
export interface IntentResult {
  l1: string;
  l2: string;
  confidence: number;
}

export interface EntranceResult {
  case: 1;
  response_mode?: string;
  data: {
    primary_intent: IntentResult;
    top_candidates: Array<{ l1: string; l2: string; probability: number }>;
    needs_clarification: boolean;
    user_output: string;
    reason: string;
  };
}

// ─── UI message unit (message + optional entrance result) ────
export interface MessageUnit {
  id: string;
  message: Message;
  entranceResult?: EntranceResult;
  stale?: boolean;
}

// ─── Conversation ────────────────────────────────────────────
export interface ConversationMeta {
  l0_threshold?: number;
  last_case?: number;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  meta: ConversationMeta;
  messages: Message[];
  results?: Record<string, EntranceResult>;
}

export interface ConversationListItem {
  id: string;
  title: string;
  msg_count: number;
  updated_at: string;
}

// ─── Workspace ───────────────────────────────────────────────
export interface StagingFile {
  id: string;
  name: string;
  size: number;
  imported_at: string;
}

export interface PersistedFile {
  name: string;
  path: string;
  size: number;
  modified_at: string;
}

export interface ParseResult {
  format: string;
  parser_used: string;
  messages: Message[];
}

// ─── SSE Events ──────────────────────────────────────────────
export interface ProgressEvent {
  stage: string;
  done?: number;
  total?: number;
  elapsed?: number;
}

export interface ChatError {
  message: string;
  traceback?: string;
}

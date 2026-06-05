// ─── OpenAI messages ────────────────────────────────────────
export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

// ─── Entrance result types ──────────────────────────────────
export interface L0Tags {
  manual: number;
  angry: number;
  sad: number;
  urgent: number;
  non_biz: number;
}

export interface Case0Data {
  call_body: string;
  situation_brief: string;
  user_comfort: string;
  l0_tags: L0Tags;
}

export interface IntentResult {
  l1: string;
  l2: string;
  confidence: number;
}

export interface SlotDef {
  name: string;
  description: string;
  options: string[];
}

export interface Slots {
  all_slots: SlotDef[];
  filled_slots: Record<string, string>;
  missing_slots: string[];
}

export interface Operation {
  type: 'clarify_slots' | 'direct_reply' | 'route_to_subsidiary' | 'fallback';
  detail: string;
}

export interface Case1Data {
  primary_intent: IntentResult;
  top_candidates: Array<{ l1: string; l2: string; probability: number }>;
  needs_clarification: boolean;
  slots: Slots;
  operation: Operation;
  user_output: string;
  reason: string;
  // V2 新增
  faq_matched?: boolean;
  audit_required?: boolean;
  recommendation?: Record<string, unknown> | null;
  tool_calls?: string[];
}

// ─── V2: Tag Disposition & Decision Trail ───────────────────
export interface TagDisposition {
  action: string;
  probability: number;
  triggered: boolean;
}

export interface DecisionTrailItem {
  step: string;
  input_value: string;
  result: string;
  reason: string;
}

export interface EntranceResultCase0 {
  case: 0;
  risk_level?: string | null;        // V2
  response_mode?: string;            // V2
  tag_dispositions?: Record<string, TagDisposition>;  // V2
  decision_trail?: DecisionTrailItem[];  // V2
  data: Case0Data;
}

export interface EntranceResultCase1 {
  case: 1;
  risk_level?: string | null;        // V2
  response_mode?: string;            // V2
  tag_dispositions?: Record<string, TagDisposition>;  // V2
  decision_trail?: DecisionTrailItem[];  // V2
  data: Case1Data;
}

// V2: case=2 紧急直通
export interface EntranceResultCase2 {
  case: 2;
  risk_level: null;
  response_mode: string;
  tag_dispositions: Record<string, TagDisposition>;
  decision_trail: DecisionTrailItem[];
  data: {
    user_output: string;
    escalate_to_human: boolean;
    primary_intent?: IntentResult;
    tool_calls?: string[];
    reason?: string;
  };
}

export type EntranceResult = EntranceResultCase0 | EntranceResultCase1 | EntranceResultCase2;

// ─── Protocol: open-ended result for future V3/V4 compatibility ──
// The GUI auto-discovers all fields from EntranceResult.
// V3/V4 kernels just add new top-level keys or data sub-keys;
// the GUI renders them without any code changes.
//
// Naming conventions for automatic renderer selection:
//   *_level         → colored risk badge (low/medium/high)
//   *_mode          → mode badge
//   *_tags, *_dispositions → key-value table
//   *_trail         → step-by-step timeline
//   *_required, *_matched → boolean badge
//   boolean values  → green/red badge
//   object/array    → expandable JSON tree
//   everything else → plain text
//
// Priority (lower = first in display):
//   0-9:   pipeline meta (case, risk_level, response_mode)
//   10-29: tag dispositions, decision trails
//   30-49: unclassified top-level keys
//   100-199: data fields from case=0 (escalation)
//   200-299: data fields from case=1/2 (L1 result)

// ─── UI message unit (message + optional entrance result) ────
export interface MessageUnit {
  id: string;
  message: Message;
  entranceResult?: EntranceResult;
  stale?: boolean;
}

// ─── Conversation ────────────────────────────────────────────
export interface ConversationMeta {
  l0_threshold: number;
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

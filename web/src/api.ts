import type { EntranceResult, ConversationListItem, Conversation, Message, StagingFile, PersistedFile, ParseResult, ProgressEvent, ChatError } from './types';

const BASE = '';  // Vite proxy handles /api → backend

// ─── Chat (V3 SSE streaming) ─────────────────────────────────
export function chatSSE(
  messages: Message[],
  debug: boolean,
  onProgress: (e: ProgressEvent) => void,
  onResult: (r: EntranceResult) => void,
  onError: (e: ChatError) => void,
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, debug }),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        onError({ message: `HTTP ${response.status}: ${response.statusText}` });
        return;
      }
      const reader = response.body?.getReader();
      if (!reader) { onError({ message: 'No response body' }); return; }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let eventType = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            const data = line.slice(6);
            try {
              const parsed = JSON.parse(data);
              if (eventType === 'progress') onProgress(parsed as ProgressEvent);
              else if (eventType === 'result') onResult(parsed as EntranceResult);
              else if (eventType === 'error') onError(parsed as ChatError);
            } catch { /* skip parse errors in partial reads */ }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError({ message: err.message || 'Network error' });
      }
    });

  return controller;
}

// ─── Conversations ───────────────────────────────────────────
export async function listConversations(): Promise<ConversationListItem[]> {
  const r = await fetch(`${BASE}/api/conversations`);
  if (!r.ok) throw new Error(`listConversations failed: ${r.status}`);
  return r.json();
}

export async function createConversation(): Promise<{ id: string; created_at: string }> {
  const r = await fetch(`${BASE}/api/conversations`, { method: 'POST' });
  if (!r.ok) throw new Error(`createConversation failed: ${r.status}`);
  return r.json();
}

export async function getConversation(id: string): Promise<Conversation> {
  const r = await fetch(`${BASE}/api/conversations/${id}`);
  if (!r.ok) throw new Error(`getConversation failed: ${r.status}`);
  return r.json();
}

export async function saveConversation(id: string, data: { messages: Message[]; meta?: Record<string, unknown>; results?: Record<string, unknown> }): Promise<void> {
  const r = await fetch(`${BASE}/api/conversations/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`saveConversation failed: ${r.status}`);
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await fetch(`${BASE}/api/conversations/${id}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`deleteConversation failed: ${r.status}`);
}

// ─── Workspace ───────────────────────────────────────────────
export async function importToStaging(file: File): Promise<StagingFile> {
  const formData = new FormData();
  formData.append('file', file);
  const r = await fetch(`${BASE}/api/workspace/import`, { method: 'POST', body: formData });
  if (!r.ok) throw new Error(`importToStaging failed: ${r.status}`);
  return r.json();
}

export async function listStaging(): Promise<StagingFile[]> {
  const r = await fetch(`${BASE}/api/workspace/staging`);
  if (!r.ok) throw new Error(`listStaging failed: ${r.status}`);
  return r.json();
}

export async function listPersisted(): Promise<PersistedFile[]> {
  const r = await fetch(`${BASE}/api/workspace/persisted`);
  if (!r.ok) throw new Error(`listPersisted failed: ${r.status}`);
  return r.json();
}

export async function persistFile(stagingId: string): Promise<PersistedFile> {
  const r = await fetch(`${BASE}/api/workspace/persist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ staging_id: stagingId }),
  });
  if (!r.ok) throw new Error(`persistFile failed: ${r.status}`);
  return r.json();
}

export async function deleteStagingFile(stagingId: string): Promise<void> {
  const r = await fetch(`${BASE}/api/workspace/staging/${stagingId}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`deleteStagingFile failed: ${r.status}`);
}

export async function parseFile(stagingId: string): Promise<ParseResult> {
  const r = await fetch(`${BASE}/api/workspace/parse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ staging_id: stagingId }),
  });
  if (!r.ok) throw new Error(`parseFile failed: ${r.status}`);
  return r.json();
}

export async function getWorkspaceConfig(): Promise<{ path: string }> {
  const r = await fetch(`${BASE}/api/workspace/config`);
  if (!r.ok) throw new Error(`getWorkspaceConfig failed: ${r.status}`);
  return r.json();
}

export async function setWorkspaceConfig(path: string): Promise<void> {
  const r = await fetch(`${BASE}/api/workspace/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) throw new Error(`setWorkspaceConfig failed: ${r.status}`);
}

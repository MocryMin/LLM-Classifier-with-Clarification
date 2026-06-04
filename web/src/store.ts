import { create } from 'zustand';
import type { Message, MessageUnit, EntranceResult, ConversationListItem, StagingFile, PersistedFile, ProgressEvent } from './types';
import { generateId, getMessageText } from './utils';
import * as api from './api';

interface AppState {
  // Current conversation
  conversationId: string | null;
  messages: MessageUnit[];
  isLoading: boolean;
  progress: ProgressEvent | null;
  error: string | null;

  // Conversation list
  conversations: ConversationListItem[];

  // Workspace
  stagingFiles: StagingFile[];
  persistedFiles: PersistedFile[];

  // UI
  leftSidebarOpen: boolean;
  rightSidebarOpen: boolean;
  l0Threshold: number;
  debugMode: boolean;

  // Actions
  sendMessage: (content: string) => Promise<void>;
  editMessage: (id: string, newContent: string) => void;
  deleteMessage: (id: string) => void;
  insertMessage: (role: 'user' | 'assistant', content: string, index: number) => void;
  resendFromIndex: (index: number) => Promise<void>;

  // Conversation mgmt
  createNewConversation: () => Promise<void>;
  loadConversation: (id: string) => Promise<void>;
  saveCurrentConversation: () => Promise<void>;
  deleteCurrentConversation: () => Promise<void>;
  refreshConversationList: () => Promise<void>;

  // Workspace mgmt
  importFile: (file: File) => Promise<void>;
  loadFileToConversation: (stagingId: string) => Promise<void>;
  removeStagingFile: (stagingId: string) => Promise<void>;
  refreshStagingFiles: () => Promise<void>;
  refreshPersistedFiles: () => Promise<void>;

  // UI toggles
  toggleLeftSidebar: () => void;
  toggleRightSidebar: () => void;
  setL0Threshold: (v: number) => void;
  setDebugMode: (v: boolean) => void;
}

export const useStore = create<AppState>((set, get) => ({
  conversationId: null,
  messages: [],
  isLoading: false,
  progress: null,
  error: null,
  conversations: [],
  stagingFiles: [],
  persistedFiles: [],
  leftSidebarOpen: true,
  rightSidebarOpen: true,
  l0Threshold: 0.7,
  debugMode: false,

  sendMessage: async (content: string) => {
    const state = get();
    // Lazily create conversation on backend when first message is sent
    let convId = state.conversationId;
    if (!convId) {
      const { id } = await api.createConversation();
      convId = id;
      set({ conversationId: id });
    }
    const newUserMsg: MessageUnit = {
      id: generateId(),
      message: { role: 'user', content },
    };
    const updatedMessages = [...state.messages, newUserMsg];
    set({ messages: updatedMessages, isLoading: true, error: null, progress: null });

    const apiMessages: Message[] = updatedMessages.map(m => m.message);

    // ★ Save user message IMMEDIATELY (before waiting for AI)
    const saveResults: Record<string, unknown> = {};
    updatedMessages.forEach((m, i) => {
      if (m.entranceResult) saveResults[String(i)] = m.entranceResult;
    });
    api.saveConversation(convId, {
      messages: apiMessages,
      meta: { l0_threshold: state.l0Threshold },
      results: Object.keys(saveResults).length > 0 ? saveResults : undefined,
    }).catch(() => {});

    // ★ Capture conversation ID in closure — response always saved to the right conversation
    const targetConvId = convId;

    api.chatSSE(
      apiMessages,
      state.l0Threshold,
      state.debugMode,
      (progress) => set({ progress }),
      (result) => {
        const aiMsg: MessageUnit = {
          id: generateId(),
          message: { role: 'assistant', content: getMessageText(result) },
          entranceResult: result,
        };

        // If user is still on same conversation, update UI
        if (get().conversationId === targetConvId) {
          const current = get().messages;
          set({ messages: [...current, aiMsg], isLoading: false, progress: null });
        } else {
          set({ isLoading: false, progress: null });
        }

        // Always save to the target conversation (even if user switched away)
        const allMessages = [...apiMessages, aiMsg.message];
        const allResults: Record<string, unknown> = {};
        updatedMessages.forEach((m, i) => {
          if (m.entranceResult) allResults[String(i)] = m.entranceResult;
        });
        allResults[String(apiMessages.length)] = result;
        api.saveConversation(targetConvId, {
          messages: allMessages,
          meta: { l0_threshold: state.l0Threshold },
          results: allResults,
        }).catch(() => {});
      },
      (error) => {
        set({ isLoading: false, error: error.message, progress: null });
      },
    );
  },

  editMessage: (id: string, newContent: string) => {
    const msgs = get().messages;
    const idx = msgs.findIndex(m => m.id === id);
    if (idx < 0) return;
    if (msgs[idx].message.content === newContent) return; // no change, skip stale marking
    const updated = msgs.slice(0, idx).concat(
      msgs.slice(idx).map((m, i) => {
        if (i === 0) return { ...m, message: { ...m.message, content: newContent } };
        if (m.message.role === 'assistant') return { ...m, stale: true, entranceResult: undefined };
        return { ...m, stale: true };
      })
    );
    set({ messages: updated });
  },

  deleteMessage: (id: string) => {
    const msgs = get().messages;
    const idx = msgs.findIndex(m => m.id === id);
    if (idx < 0) return;
    const updated = msgs.filter((_, i) => i !== idx);
    for (let i = idx; i < updated.length; i++) {
      if (updated[i].message.role === 'assistant' && updated[i].entranceResult !== undefined) {
        updated[i] = { ...updated[i], stale: true, entranceResult: undefined };
      }
    }
    set({ messages: updated });
  },

  insertMessage: (role, content, index) => {
    const msgs = [...get().messages];
    const newMsg: MessageUnit = {
      id: generateId(),
      message: { role, content },
    };
    msgs.splice(index, 0, newMsg);
    for (let i = index + 1; i < msgs.length; i++) {
      if (msgs[i].message.role === 'assistant') {
        msgs[i] = { ...msgs[i], stale: true, entranceResult: undefined };
      }
    }
    set({ messages: msgs });
  },

  resendFromIndex: async (index: number) => {
    const state = get();
    const convId = state.conversationId;
    const msgsToSend = state.messages.slice(0, index).map(m => m.message);
    set({ isLoading: true, error: null, progress: null });

    // Save truncated state immediately
    if (convId) {
      api.saveConversation(convId, {
        messages: msgsToSend,
        meta: { l0_threshold: state.l0Threshold },
      }).catch(() => {});
    }

    const targetConvId = convId;

    api.chatSSE(
      msgsToSend,
      state.l0Threshold,
      state.debugMode,
      (progress) => set({ progress }),
      (result) => {
        const aiMsg: MessageUnit = {
          id: generateId(),
          message: { role: 'assistant', content: getMessageText(result) },
          entranceResult: result,
        };

        if (get().conversationId === targetConvId) {
          const truncated = get().messages.slice(0, index);
          set({ messages: [...truncated, aiMsg], isLoading: false, progress: null });
        } else {
          set({ isLoading: false, progress: null });
        }

        // Always save to target conversation
        if (targetConvId) {
          const allMessages = [...msgsToSend, aiMsg.message];
          const allResults: Record<string, unknown> = {};
          allResults[String(msgsToSend.length)] = result;
          api.saveConversation(targetConvId, {
            messages: allMessages,
            meta: { l0_threshold: state.l0Threshold },
            results: allResults,
          }).catch(() => {});
        }
      },
      (error) => {
        set({ isLoading: false, error: error.message, progress: null });
      },
    );
  },

  createNewConversation: async () => {
    set({
      conversationId: null,
      messages: [],
      error: null,
      progress: null,
    });
  },

  loadConversation: async (id: string) => {
    const conv = await api.getConversation(id);
    const results = conv.results || {};
    const units: MessageUnit[] = conv.messages.map((m, i) => ({
      id: generateId(),
      message: m,
      entranceResult: results[String(i)] as EntranceResult | undefined,
    }));
    set({
      conversationId: id,
      messages: units,
      l0Threshold: conv.meta?.l0_threshold ?? get().l0Threshold,
    });
  },

  saveCurrentConversation: async () => {
    const { conversationId, messages, l0Threshold } = get();
    if (!conversationId) return;
    // Collect entrance results keyed by message index
    const results: Record<string, unknown> = {};
    messages.forEach((m, i) => {
      if (m.entranceResult) results[String(i)] = m.entranceResult;
    });
    await api.saveConversation(conversationId, {
      messages: messages.map(m => m.message),
      meta: { l0_threshold: l0Threshold },
      results: Object.keys(results).length > 0 ? results : undefined,
    });
    get().refreshConversationList();
  },

  deleteCurrentConversation: async () => {
    const { conversationId } = get();
    if (!conversationId) return;
    try {
      await api.deleteConversation(conversationId);
    } catch (e) {
      console.error('Delete failed:', e);
    }
    set({ conversationId: null, messages: [], error: null });
    get().refreshConversationList();
  },

  refreshConversationList: async () => {
    try {
      const list = await api.listConversations();
      set({ conversations: list });
    } catch { /* silently fail */ }
  },

  importFile: async (file: File) => {
    await api.importToStaging(file);
    get().refreshStagingFiles();
  },

  loadFileToConversation: async (stagingId: string) => {
    const parsed = await api.parseFile(stagingId);
    await api.persistFile(stagingId);
    const { id } = await api.createConversation();
    const units: MessageUnit[] = parsed.messages.map(m => ({
      id: generateId(),
      message: m,
    }));
    set({
      conversationId: id,
      messages: units,
      error: null,
    });
    get().refreshConversationList();
    get().refreshStagingFiles();
    get().refreshPersistedFiles();
  },

  removeStagingFile: async (stagingId: string) => {
    await api.deleteStagingFile(stagingId);
    get().refreshStagingFiles();
  },

  refreshStagingFiles: async () => {
    try {
      set({ stagingFiles: await api.listStaging() });
    } catch { /* silently fail */ }
  },

  refreshPersistedFiles: async () => {
    try {
      set({ persistedFiles: await api.listPersisted() });
    } catch { /* silently fail */ }
  },

  toggleLeftSidebar: () => set(s => ({ leftSidebarOpen: !s.leftSidebarOpen })),
  toggleRightSidebar: () => set(s => ({ rightSidebarOpen: !s.rightSidebarOpen })),
  setL0Threshold: (v) => set({ l0Threshold: v }),
  setDebugMode: (v) => set({ debugMode: v }),
}));

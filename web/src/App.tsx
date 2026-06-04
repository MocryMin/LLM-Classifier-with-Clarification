import { useEffect } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toaster'
import { useStore } from '@/store'
import * as api from '@/api'
import LayoutShell from '@/components/LayoutShell'
import ConversationSidebar from '@/components/ConversationSidebar'
import ChatMain from '@/components/ChatMain'
import ThresholdSettings from '@/components/ThresholdSettings'
import WorkspaceSidebar from '@/components/WorkspaceSidebar'

export default function App() {
  const { createNewConversation, toggleLeftSidebar, toggleRightSidebar, saveCurrentConversation } = useStore()

  useEffect(() => {
    const init = async () => {
      try {
        const list = await api.listConversations();
        if (list.length > 0) {
          // Load most recent conversation
          useStore.getState().loadConversation(list[0].id);
        } else {
          // No conversations exist yet, start empty (don't create until first message)
          useStore.setState({ conversationId: null, messages: [] });
        }
      } catch {
        useStore.setState({ conversationId: null, messages: [] });
      }
    };
    init();
  }, [])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'b') { e.preventDefault(); toggleLeftSidebar(); }
      if (e.ctrlKey && e.shiftKey && e.key === 'B') { e.preventDefault(); toggleRightSidebar(); }
      if (e.ctrlKey && e.key === 'n') { e.preventDefault(); createNewConversation(); }
      if (e.ctrlKey && e.key === 's') { e.preventDefault(); saveCurrentConversation(); }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggleLeftSidebar, toggleRightSidebar, createNewConversation, saveCurrentConversation]);

  return (
    <TooltipProvider delayDuration={300}>
      <LayoutShell
        leftSidebar={<ConversationSidebar />}
        main={
          <>
            <ThresholdSettings />
            <ChatMain />
          </>
        }
        rightSidebar={<WorkspaceSidebar />}
      />
      <Toaster />
    </TooltipProvider>
  )
}

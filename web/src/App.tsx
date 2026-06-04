import { useEffect } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toaster'
import { useStore } from '@/store'
import LayoutShell from '@/components/LayoutShell'
import ConversationSidebar from '@/components/ConversationSidebar'
import ChatMain from '@/components/ChatMain'
import ThresholdSettings from '@/components/ThresholdSettings'
import WorkspaceSidebar from '@/components/WorkspaceSidebar'

export default function App() {
  const { createNewConversation, conversationId, toggleLeftSidebar, toggleRightSidebar, saveCurrentConversation } = useStore()

  useEffect(() => {
    if (!conversationId) {
      createNewConversation()
    }
  }, [conversationId, createNewConversation])

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

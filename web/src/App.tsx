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
  const { createNewConversation, conversationId } = useStore()

  useEffect(() => {
    if (!conversationId) {
      createNewConversation()
    }
  }, [conversationId, createNewConversation])

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

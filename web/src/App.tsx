import { useEffect } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toaster'
import { useStore } from '@/store'
import ChatMain from '@/components/ChatMain'

export default function App() {
  const { createNewConversation, conversationId } = useStore()

  useEffect(() => {
    if (!conversationId) {
      createNewConversation()
    }
  }, [conversationId, createNewConversation])

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-screen bg-gray-950 text-gray-100">
        <ChatMain />
      </div>
      <Toaster />
    </TooltipProvider>
  )
}

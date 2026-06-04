import { useStore } from '@/store'
import MessageList from './MessageList'
import ChatInput from './ChatInput'
import { Button } from '@/components/ui/button'
import { RefreshCw, Loader2 } from 'lucide-react'

export default function ChatMain() {
  const { isLoading, progress, error, refreshConversationList, conversationId } = useStore()

  const progressLabel = progress
    ? progress.stage === 'l0_start' ? 'L0 标签检测中...'
    : progress.stage === 'l1' ? 'L1 意图路由中...'
    : progress.stage === 'escalation' ? '生成升级处置...'
    : `${progress.stage}...`
    : null

  return (
    <div className="flex flex-col flex-1 min-w-0">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800 bg-gray-950">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-medium text-gray-300">
            {conversationId ? `对话 ${conversationId.slice(0, 8)}...` : '新建对话'}
          </h2>
          {isLoading && progressLabel && (
            <span className="flex items-center gap-1 text-xs text-blue-400">
              <Loader2 className="h-3 w-3 animate-spin" />
              {progressLabel}
            </span>
          )}
        </div>
        <Button variant="ghost" size="sm" onClick={() => refreshConversationList()} title="刷新列表">
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Progress bar (thin) */}
      {isLoading && (
        <div className="h-0.5 bg-gray-800">
          <div className="h-full bg-blue-600 animate-pulse" style={{ width: '60%' }} />
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mx-4 mt-2 px-3 py-2 rounded-md bg-red-950 border border-red-800 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Messages */}
      <MessageList />

      {/* Input */}
      <ChatInput />
    </div>
  )
}

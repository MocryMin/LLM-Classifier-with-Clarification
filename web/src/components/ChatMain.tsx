import { useStore } from '@/store'
import MessageList from './MessageList'
import ChatInput from './ChatInput'
import { Loader2 } from 'lucide-react'

export default function ChatMain() {
  const { isLoading, progress, error } = useStore()

  const progressLabel = progress
    ? progress.stage === 'l0_start' ? 'L0 标签检测中...'
    : progress.stage === 'l1' ? 'L1 意图路由中...'
    : progress.stage === 'escalation' ? '生成升级处置...'
    : `${progress.stage}...`
    : null

  return (
    <div className="flex flex-col flex-1 min-w-0">
      {/* Loading indicator */}
      {isLoading && progressLabel && (
        <div className="flex items-center gap-2 px-4 py-1.5 bg-blue-950/50 border-b border-blue-900">
          <Loader2 className="h-3 w-3 animate-spin text-blue-400" />
          <span className="text-xs text-blue-400">{progressLabel}</span>
        </div>
      )}

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

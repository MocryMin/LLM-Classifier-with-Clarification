import { MessageSquare } from 'lucide-react'
import { cn, formatTimestamp } from '@/utils'

interface Props {
  id: string
  title: string
  msgCount: number
  updatedAt: string
  isActive: boolean
  onClick: () => void
}

export default function ConversationItem({ title, msgCount, updatedAt, isActive, onClick }: Props) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'flex items-start gap-2 px-3 py-2.5 rounded-md cursor-pointer transition-colors',
        isActive ? 'bg-blue-600/20 border border-blue-800' : 'hover:bg-gray-900 border border-transparent',
      )}
    >
      <MessageSquare className="h-4 w-4 mt-0.5 shrink-0 text-gray-500" />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-200 truncate">{title}</p>
        <p className="text-xs text-gray-600 mt-0.5">
          {msgCount} 条消息 · {formatTimestamp(updatedAt)}
        </p>
      </div>
    </div>
  )
}

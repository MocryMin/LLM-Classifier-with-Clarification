import { useState } from 'react'
import { Pencil, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { MessageUnit as MessageUnitType } from '@/types'
import { useStore } from '@/store'
import { cn } from '@/utils'

interface Props {
  unit: MessageUnitType
  index: number
}

export default function MessageUnit({ unit, index }: Props) {
  const { editMessage, deleteMessage } = useStore()
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState(unit.message.content)

  const isUser = unit.message.role === 'user'

  const handleSaveEdit = () => {
    editMessage(unit.id, editValue)
    setEditing(false)
  }

  const handleDoubleClick = () => {
    if (isUser) {
      setEditValue(unit.message.content)
      setEditing(true)
    }
  }

  return (
    <div
      className={cn(
        'group relative flex gap-3 px-4 py-3 transition-colors hover:bg-gray-900/50',
        unit.stale && 'border-2 border-dashed border-gray-700 opacity-60',
      )}
    >
      {/* Avatar */}
      <div className={cn(
        'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold',
        isUser ? 'bg-blue-600 text-white' : 'bg-emerald-600 text-white',
      )}>
        {isUser ? '👤' : '🤖'}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0" onDoubleClick={handleDoubleClick}>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-semibold text-gray-400">
            {isUser ? '用户' : '小保'}
          </span>
          {unit.stale && <span className="text-xs text-yellow-500">已过期</span>}
        </div>

        {editing ? (
          <div className="flex flex-col gap-2">
            <textarea
              value={editValue}
              onChange={e => setEditValue(e.target.value)}
              className="w-full min-h-[60px] rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-600"
              autoFocus
              onBlur={handleSaveEdit}
              onKeyDown={e => { if (e.key === 'Escape') setEditing(false); if (e.key === 'Enter' && e.ctrlKey) handleSaveEdit(); }}
            />
            <span className="text-xs text-gray-500">Ctrl+Enter 保存 · Escape 取消</span>
          </div>
        ) : (
          <div className="text-sm text-gray-200 whitespace-pre-wrap leading-relaxed">
            {unit.message.content}
          </div>
        )}
      </div>

      {/* Hover actions */}
      <div className="absolute right-3 top-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {isUser && !editing && (
          <Button variant="ghost" size="icon" onClick={() => { setEditValue(unit.message.content); setEditing(true); }} title="编辑">
            <Pencil className="h-3.5 w-3.5" />
          </Button>
        )}
        <Button variant="ghost" size="icon" onClick={() => deleteMessage(unit.id)} title="删除">
          <Trash2 className="h-3.5 w-3.5 text-red-400" />
        </Button>
      </div>
    </div>
  )
}

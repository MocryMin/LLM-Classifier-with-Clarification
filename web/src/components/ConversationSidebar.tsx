import { useEffect, useState } from 'react'
import { Plus, Search, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useStore } from '@/store'
import ConversationItem from './ConversationItem'

export default function ConversationSidebar() {
  const { conversations, createNewConversation, loadConversation, deleteCurrentConversation, conversationId, refreshConversationList } = useStore()
  const [search, setSearch] = useState('')

  useEffect(() => {
    refreshConversationList()
  }, [refreshConversationList])

  const filtered = search
    ? conversations.filter(c => c.title.toLowerCase().includes(search.toLowerCase()))
    : conversations

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
        <span className="text-sm font-semibold text-gray-300">对话列表</span>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={createNewConversation} title="新建对话">
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      {/* Search */}
      <div className="px-3 py-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
          <Input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="搜索对话..."
            className="pl-7 h-8 text-xs"
          />
        </div>
      </div>

      {/* List */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        <div className="px-2 py-1">
          {filtered.length === 0 && (
            <p className="text-xs text-gray-600 text-center py-8">
              {search ? '没有匹配的对话' : '暂无对话，点击 + 创建'}
            </p>
          )}
          {filtered.map(c => (
            <ConversationItem
              key={c.id}
              id={c.id}
              title={c.title}
              msgCount={c.msg_count}
              updatedAt={c.updated_at}
              isActive={c.id === conversationId}
              onClick={() => loadConversation(c.id)}
            />
          ))}
        </div>
      </div>

      {/* Footer actions */}
      {conversationId && (
        <div className="px-3 py-2 border-t border-gray-800">
          <Button variant="ghost" size="sm" className="w-full text-xs text-red-400 hover:text-red-300" onClick={deleteCurrentConversation}>
            <Trash2 className="h-3.5 w-3.5 mr-1" />
            删除当前对话
          </Button>
        </div>
      )}
    </div>
  )
}

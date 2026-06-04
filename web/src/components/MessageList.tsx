import { useEffect, useRef } from 'react'
import { useStore } from '@/store'
import MessageUnit from './MessageUnit'

export default function MessageList() {
  const { messages } = useStore()
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages.length])

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500">
        <div className="text-center">
          <div className="text-4xl mb-4">🤖</div>
          <p className="text-lg font-medium text-gray-400">智能管家 · 对话测试工作台</p>
          <p className="text-sm mt-1 text-gray-600">发送消息开始测试 entrance 全链路</p>
        </div>
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden" style={{ overscrollBehavior: 'contain' }}>
      <div className="max-w-3xl mx-auto py-4">
        {messages.map((unit, i) => (
          <MessageUnit key={unit.id} unit={unit} index={i} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

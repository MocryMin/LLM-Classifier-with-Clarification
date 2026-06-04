import { useState, useRef, KeyboardEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Send, Loader2 } from 'lucide-react'
import { useStore } from '@/store'

export default function ChatInput() {
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const { sendMessage, isLoading } = useStore()

  const handleSend = () => {
    const text = value.trim()
    if (!text || isLoading) return
    sendMessage(text)
    setValue('')
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex items-center gap-2 px-4 py-3 border-t border-gray-800 bg-gray-950">
      <Input
        ref={inputRef}
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入消息... (Enter 发送，Shift+Enter 换行)"
        disabled={isLoading}
        className="flex-1 bg-gray-900 border-gray-700 focus-visible:ring-blue-600"
      />
      <Button onClick={handleSend} disabled={isLoading || !value.trim()} size="icon">
        {isLoading ? <Loader2 className="animate-spin" /> : <Send />}
      </Button>
    </div>
  )
}

import { FileJson, FileText, X, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { StagingFile } from '@/types'
import { useStore } from '@/store'
import { useState } from 'react'

interface Props { file: StagingFile }

export default function StagingFileItem({ file }: Props) {
  const { loadFileToConversation, removeStagingFile } = useStore()
  const [loading, setLoading] = useState(false)

  const isJson = file.name.endsWith('.json')
  const Icon = isJson ? FileJson : FileText

  const handleLoad = async () => {
    setLoading(true)
    try {
      await loadFileToConversation(file.id)
    } catch {
      // silently fail
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-gray-900 cursor-pointer group transition-colors"
      onDoubleClick={handleLoad}
      draggable
      onDragStart={e => { e.dataTransfer.setData('text/plain', file.id) }}
      title="双击加载对话 · 拖拽到对话列表"
    >
      <Icon className="h-3.5 w-3.5 text-gray-500 shrink-0" />
      <span className="text-xs text-gray-300 truncate flex-1">{file.name}</span>
      {loading && <Loader2 className="h-3 w-3 animate-spin text-blue-400" />}
      <Button variant="ghost" size="icon" className="h-5 w-5 opacity-0 group-hover:opacity-100" onClick={e => { e.stopPropagation(); removeStagingFile(file.id); }}>
        <X className="h-3 w-3 text-gray-500" />
      </Button>
    </div>
  )
}

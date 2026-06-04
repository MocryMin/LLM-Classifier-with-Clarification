import { FileJson, FileText, ExternalLink } from 'lucide-react'
import type { PersistedFile } from '@/types'
import { formatTimestamp } from '@/utils'

interface Props { file: PersistedFile }

export default function PersistedFileItem({ file }: Props) {
  const isJson = file.name.endsWith('.json')
  const Icon = isJson ? FileJson : FileText

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-gray-900 group transition-colors">
      <Icon className="h-3.5 w-3.5 text-gray-500 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-xs text-gray-300 truncate">{file.name}</p>
        <p className="text-[10px] text-gray-600">{formatTimestamp(file.modified_at)}</p>
      </div>
      <ExternalLink className="h-3 w-3 text-gray-600 opacity-0 group-hover:opacity-100" />
    </div>
  )
}

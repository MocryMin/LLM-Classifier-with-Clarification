import { useEffect, useRef } from 'react'
import { FolderOpen, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { useStore } from '@/store'
import StagingFileItem from './StagingFileItem'
import PersistedFileItem from './PersistedFileItem'

export default function WorkspaceSidebar() {
  const { stagingFiles, persistedFiles, importFile, refreshStagingFiles, refreshPersistedFiles } = useStore()
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    refreshStagingFiles()
    refreshPersistedFiles()
  }, [refreshStagingFiles, refreshPersistedFiles])

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return
    for (let i = 0; i < files.length; i++) {
      await importFile(files[i])
    }
    e.target.value = ''
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    const files = e.dataTransfer.files
    for (let i = 0; i < files.length; i++) {
      await importFile(files[i])
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800">
        <FolderOpen className="h-4 w-4 text-gray-400" />
        <span className="text-sm font-semibold text-gray-300 flex-1">工作文件夹</span>
        <input type="file" ref={fileInputRef} onChange={handleFileChange} className="hidden" multiple accept=".json,.jsonl,.txt" />
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => fileInputRef.current?.click()} title="导入文件">
          <Upload className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        {/* Staging area */}
        <div className="px-3 py-2">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">暂存区</p>
          {stagingFiles.length === 0 && (
            <p className="text-xs text-gray-700 py-2">拖入文件到此处导入</p>
          )}
          {stagingFiles.map(f => (
            <StagingFileItem key={f.id} file={f} />
          ))}
        </div>

        <Separator />

        {/* Persisted area */}
        <div className="px-3 py-2">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">已加载</p>
          {persistedFiles.length === 0 && (
            <p className="text-xs text-gray-700 py-2">暂存文件加载后出现在此处</p>
          )}
          {persistedFiles.map(f => (
            <PersistedFileItem key={f.name} file={f} />
          ))}
        </div>
      </div>
    </div>
  )
}

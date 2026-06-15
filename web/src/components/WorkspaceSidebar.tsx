import { useEffect, useRef } from 'react'
import { FolderOpen, RefreshCw, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useStore } from '@/store'
import type { WorkspaceFile } from '@/api'

export default function WorkspaceSidebar() {
  const { workspacePath, workspaceFiles, setWorkspacePath, browseWorkspace, loadFileToConversation } = useStore()
  const pathInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    browseWorkspace()
  }, [browseWorkspace])

  const handlePathChange = () => {
    const newPath = pathInputRef.current?.value?.trim()
    if (newPath) setWorkspacePath(newPath)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handlePathChange()
  }

  const handleDoubleClick = (file: WorkspaceFile) => {
    loadFileToConversation(file.path)
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800">
        <FolderOpen className="h-4 w-4 text-gray-400 shrink-0" />
        <span className="text-sm font-semibold text-gray-300 flex-1">工作文件夹</span>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => browseWorkspace()} title="刷新">
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Path input */}
      <div className="px-3 py-2 border-b border-gray-800/50">
        <input
          ref={pathInputRef}
          type="text"
          defaultValue={workspacePath}
          onKeyDown={handleKeyDown}
          onBlur={handlePathChange}
          placeholder="输入文件夹路径, 回车确认..."
          className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300 placeholder-gray-600 focus:outline-none focus:border-blue-600"
        />
      </div>

      {/* File list */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        {workspaceFiles.length === 0 ? (
          <p className="text-xs text-gray-700 px-3 py-4">
            输入文件夹路径后回车, 即可浏览其中文件
          </p>
        ) : (
          <div className="px-3 py-2">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">
              {workspaceFiles.length} 个文件
            </p>
            {workspaceFiles.map(f => (
              <div
                key={f.path}
                className="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer hover:bg-gray-800/50 transition-colors group"
                onDoubleClick={() => handleDoubleClick(f)}
                title={`双击加载: ${f.name}`}
              >
                <FileText className="h-3.5 w-3.5 text-gray-500 shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-300 truncate">{f.name}</p>
                  <p className="text-[10px] text-gray-600">{formatSize(f.size)}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

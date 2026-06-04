import { ReactNode } from 'react'
import { PanelLeft, PanelRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useStore } from '@/store'
import { cn } from '@/utils'

interface Props {
  leftSidebar: ReactNode
  main: ReactNode
  rightSidebar: ReactNode
}

export default function LayoutShell({ leftSidebar, main, rightSidebar }: Props) {
  const { leftSidebarOpen, rightSidebarOpen, toggleLeftSidebar, toggleRightSidebar } = useStore()

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Left sidebar */}
      <div className={cn(
        'flex flex-col border-r border-gray-800 bg-gray-950 transition-all duration-200 overflow-hidden',
        leftSidebarOpen ? 'w-72' : 'w-0 overflow-hidden border-r-0',
      )}>
        {leftSidebarOpen && leftSidebar}
      </div>

      {/* Main area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Toggle buttons row */}
        <div className="flex items-center gap-1 px-2 py-1 border-b border-gray-800">
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleLeftSidebar} title="切换对话列表">
            <PanelLeft className={cn('h-4 w-4', !leftSidebarOpen && 'text-gray-600')} />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7 ml-auto" onClick={toggleRightSidebar} title="切换工作文件夹">
            <PanelRight className={cn('h-4 w-4', !rightSidebarOpen && 'text-gray-600')} />
          </Button>
        </div>
        {main}
      </div>

      {/* Right sidebar */}
      <div className={cn(
        'flex flex-col border-l border-gray-800 bg-gray-950 transition-all duration-200 overflow-hidden',
        rightSidebarOpen ? 'w-72' : 'w-0 overflow-hidden border-l-0',
      )}>
        {rightSidebarOpen && rightSidebar}
      </div>
    </div>
  )
}

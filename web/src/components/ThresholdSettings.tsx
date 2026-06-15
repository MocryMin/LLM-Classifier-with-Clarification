import { useStore } from '@/store'

export default function ThresholdSettings() {
  const { debugMode, setDebugMode } = useStore()

  return (
    <div className="flex items-center gap-4 px-4 py-2 border-b border-gray-800 bg-gray-950">
      <span className="text-xs text-emerald-400 font-medium">V3 意图路由</span>

      <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
        <input
          type="checkbox"
          checked={debugMode}
          onChange={e => setDebugMode(e.target.checked)}
          className="accent-blue-600"
        />
        Debug
      </label>
    </div>
  )
}

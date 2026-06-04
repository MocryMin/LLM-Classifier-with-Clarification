import { useStore } from '@/store'

export default function ThresholdSettings() {
  const { l0Threshold, setL0Threshold, debugMode, setDebugMode } = useStore()

  return (
    <div className="flex items-center gap-4 px-4 py-2 border-b border-gray-800 bg-gray-950">
      <div className="flex items-center gap-2">
        <label className="text-xs text-gray-500">L0 阈值: <span className="text-gray-300 font-mono">{l0Threshold.toFixed(1)}</span></label>
        <input
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={l0Threshold}
          onChange={e => setL0Threshold(parseFloat(e.target.value))}
          className="w-20 h-1 accent-blue-600"
        />
      </div>
      <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
        <input type="checkbox" checked={debugMode} onChange={e => setDebugMode(e.target.checked)} className="accent-blue-600" />
        Debug
      </label>
    </div>
  )
}

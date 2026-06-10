import { useStore } from '@/store'

export default function ThresholdSettings() {
  const { l0Threshold, setL0Threshold, debugMode, setDebugMode, useV3, setUseV3 } = useStore()

  return (
    <div className="flex items-center gap-4 px-4 py-2 border-b border-gray-800 bg-gray-950">
      {/* V2/V3 toggle */}
      <label className="flex items-center gap-1.5 text-xs cursor-pointer">
        <input
          type="checkbox"
          checked={useV3}
          onChange={e => setUseV3(e.target.checked)}
          className="accent-emerald-600"
        />
        <span className={useV3 ? 'text-emerald-400 font-medium' : 'text-gray-500'}>
          V3
        </span>
      </label>

      {/* L0 threshold — only relevant for V2 */}
      {!useV3 && (
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">
            L0 阈值: <span className="text-gray-300 font-mono">{l0Threshold.toFixed(1)}</span>
          </label>
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
      )}

      {/* Debug */}
      <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
        <input type="checkbox" checked={debugMode} onChange={e => setDebugMode(e.target.checked)} className="accent-blue-600" />
        Debug
      </label>
    </div>
  )
}

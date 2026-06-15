import { useState, useEffect } from 'react'
import { ChevronDown, ChevronRight, Copy, HelpCircle, AlertTriangle, CheckCircle, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { EntranceResult } from '@/types'
import { cn, formatJson, truncateText } from '@/utils'

// ============================================================
// Convention over Configuration Protocol
// ============================================================
// The GUI auto-discovers ALL fields from EntranceResult.
// No GUI code changes needed when V3/V4/V5 kernels add new fields.
//
// Kernel contract (3 rules):
//   1. Return { case, risk_level?, response_mode?, data: {...}, ... }
//   2. Top-level keys use snake_case; GUI auto-discovers them
//   3. Naming suffixes control renderer choice:
//        *_level         → colored risk badge
//        *_mode          → mode badge
//        *_tags, *_dispositions → key-value table
//        *_trail         → step-by-step timeline
//        *_required, *_matched → boolean badge
//        boolean values  → green/red badge
//        object/array    → expandable JSON tree
//        number/string   → plain text
// ============================================================

// ─── Render hint types ─────────────────────────────────────────
type RenderHint = 'badge:risk' | 'badge:mode' | 'badge:bool' | 'table' | 'timeline' | 'json' | 'text'

function detectHint(key: string, value: unknown): RenderHint {
  if (key.endsWith('_level') && typeof value === 'string') return 'badge:risk'
  if (key.endsWith('_mode') && typeof value === 'string') return 'badge:mode'
  if (key.endsWith('_required') || key.endsWith('_matched') ||
      key.endsWith('_to_human')) return 'badge:bool'
  if (typeof value === 'boolean') return 'badge:bool'
  if ((key.endsWith('_tags') || key.endsWith('_dispositions')) &&
      typeof value === 'object' && value !== null) return 'table'
  if (key.endsWith('_trail') && Array.isArray(value)) return 'timeline'
  if (key.endsWith('_candidates') && Array.isArray(value)) return 'table'
  if (typeof value === 'object' && value !== null) return 'json'
  return 'text'
}

// ─── Priority ordering ─────────────────────────────────────────
function getPriority(key: string, isTopLevel: boolean): number {
  const PRIORITY: Record<string, number> = {
    // Pipeline meta
    case: 0, response_mode: 2,
    // L1 result (data)
    primary_intent: 200, top_candidates: 201,
    needs_clarification: 202,
    user_output: 205, reason: 206,
  }
  if (key in PRIORITY) return PRIORITY[key]
  // Unknown top-level keys go between pipeline meta and data
  // Unknown data keys go at the end
  return isTopLevel ? 50 : 300
}

// ─── Help text ──────────────────────────────────────────────────
const HELP: Record<string, string> = {
  case: '路由结果。1=正常路由',
  response_mode: '回复模式。v3=V3统一路由',
  primary_intent: 'L1分类的主导意图（一级/二级/置信度）',
  top_candidates: '概率>0.1的候选意图列表',
  needs_clarification: '是否需要向用户发起澄清',
  user_output: '面向用户的输出文本（含 ###call(L1-L2) 路由标记）',
  reason: '判断依据',
}

function getHelp(key: string): string {
  if (key in HELP) return HELP[key]
  return `自动发现字段: ${key}`
}

// ─── Field definition ───────────────────────────────────────────
interface FieldDef {
  key: string
  label: string
  value: unknown
  help: string
  hint: RenderHint
}

function extractFields(result: EntranceResult): FieldDef[] {
  const fields: FieldDef[] = []
  const resultObj = result as Record<string, unknown>
  const data = resultObj.data as Record<string, unknown> | undefined

  // Collect top-level keys (except 'data')
  for (const key of Object.keys(resultObj)) {
    if (key === 'data') continue
    const value = resultObj[key]
    fields.push({
      key, label: key, value,
      help: getHelp(key),
      hint: detectHint(key, value),
    })
  }

  // Collect data sub-keys
  if (data && typeof data === 'object') {
    for (const key of Object.keys(data)) {
      fields.push({
        key, label: key, value: data[key],
        help: getHelp(key),
        hint: detectHint(key, data[key]),
      })
    }
  }

  // Sort by priority
  fields.sort((a, b) => {
    const pa = getPriority(a.key, a.label === a.key && !(resultObj.data && a.key in (resultObj.data as Record<string, unknown>)))
    const pb = getPriority(b.key, b.label === b.key && !(resultObj.data && b.key in (resultObj.data as Record<string, unknown>)))
    return pa - pb
  })

  return fields
}

// ============================================================
// Value Renderers
// ============================================================

function RiskBadge({ level }: { level: string }) {
  const colors: Record<string, string> = {
    low: 'bg-emerald-900/60 text-emerald-300 border-emerald-700',
    medium: 'bg-amber-900/60 text-amber-300 border-amber-700',
    high: 'bg-red-900/60 text-red-300 border-red-700',
  }
  const labels: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' }
  return (
    <span className={cn('text-[10px] px-1.5 py-0 border rounded font-mono font-medium', colors[level] || 'bg-gray-800 text-gray-400')}>
      {labels[level] || level}
    </span>
  )
}

function ModeBadge({ mode }: { mode: string }) {
  const labels: Record<string, string> = {
    generative: '生成式', faq_first: 'FAQ优先',
    faq_only_human: 'FAQ+人工', direct_guide: '紧急直通',
    v3: 'V3路由',
  }
  return (
    <span className="text-[10px] px-1.5 py-0 border border-gray-600 rounded font-mono text-gray-400">
      {labels[mode] || mode}
    </span>
  )
}

function BoolBadge({ value }: { value: unknown }) {
  const v = Boolean(value)
  return (
    <span className={cn(
      'inline-flex items-center gap-1 text-xs font-mono',
      v ? 'text-emerald-400' : 'text-red-400',
    )}>
      {v ? <CheckCircle className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
      {String(v)}
    </span>
  )
}

function TagTable({ value }: { value: unknown }) {
  const obj = value as Record<string, unknown>
  const entries = Object.entries(obj)

  // Detect table type by inspecting nested object structure
  const firstNested = entries.length > 0 && typeof entries[0][1] === 'object' && entries[0][1] !== null
    ? (entries[0][1] as Record<string, unknown>)
    : null

  // Case A: intent candidates (objects with l1/l2 keys) → rank | l1 | l2 | prob
  const isCandidateList = firstNested && 'l1' in firstNested && 'l2' in firstNested

  // Case B: tag dispositions (objects with action key) → tag | action | prob | 触发
  const isDisposition = firstNested && 'action' in firstNested

  if (isCandidateList) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-right py-1 pr-2 font-medium w-6">#</th>
              <th className="text-left py-1 pr-2 font-medium">l1</th>
              <th className="text-left py-1 pr-2 font-medium">l2</th>
              <th className="text-right py-1 font-medium">prob</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([idx, info], i) => {
              const d = info as Record<string, unknown>
              const isTop = i === 0
              return (
                <tr key={idx} className={cn('border-b border-gray-800/50', isTop && 'bg-emerald-900/20')}>
                  <td className="py-1 pr-2 text-right text-gray-500 font-mono">{Number(idx) + 1}</td>
                  <td className="py-1 pr-2 text-gray-400 font-mono text-[10px]">{String(d.l1 || '-')}</td>
                  <td className="py-1 pr-2 text-gray-300 font-mono">{String(d.l2 || '-')}</td>
                  <td className="py-1 text-right text-gray-300 font-mono">
                    {typeof d.probability === 'number' ? d.probability.toFixed(2) : '-'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    )
  }

  if (isDisposition) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-left py-1 pr-2 font-medium">tag</th>
              <th className="text-left py-1 pr-2 font-medium">action</th>
              <th className="text-right py-1 pr-2 font-medium">prob</th>
              <th className="text-center py-1 font-medium">触发</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([tag, info]) => {
              const d = info as Record<string, unknown>
              const triggered = Boolean(d.triggered)
              return (
                <tr key={tag} className={cn('border-b border-gray-800/50', triggered && 'bg-amber-900/20')}>
                  <td className="py-1 pr-2 text-gray-300 font-mono">{tag}</td>
                  <td className="py-1 pr-2 text-blue-300 font-mono text-[10px]">{String(d.action || '-')}</td>
                  <td className="py-1 pr-2 text-right text-gray-400 font-mono">
                    {typeof d.probability === 'number' ? d.probability.toFixed(2) : '-'}
                  </td>
                  <td className="py-1 text-center">
                    {triggered
                      ? <AlertTriangle className="h-3 w-3 text-amber-400 inline" />
                      : <span className="text-gray-600">-</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    )
  }

  // Simple key-value table
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k} className="border-b border-gray-800/50">
              <td className="py-1 pr-3 text-gray-400 font-mono whitespace-nowrap align-top">{k}</td>
              <td className="py-1 text-gray-300 font-mono break-all">
                {typeof v === 'object' ? formatJson(v) : String(v)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TrailTimeline({ value }: { value: unknown }) {
  const items = value as Array<Record<string, unknown>>
  if (!Array.isArray(items) || items.length === 0) {
    return <span className="text-gray-600 italic text-xs">(空)</span>
  }

  return (
    <div className="space-y-1">
      {items.map((item, i) => (
        <div key={i} className="flex gap-2 text-xs">
          {/* Step number */}
          <div className="flex flex-col items-center shrink-0 pt-0.5">
            <div className="w-4 h-4 rounded-full bg-gray-700 flex items-center justify-center text-[10px] text-gray-300 font-mono">
              {i + 1}
            </div>
            {i < items.length - 1 && <div className="w-px flex-1 bg-gray-700 my-0.5" />}
          </div>
          {/* Content */}
          <div className="flex-1 min-w-0 pb-1.5">
            <div className="flex items-center gap-1.5">
              <span className="text-blue-300 font-mono text-[10px]">{String(item.step || '?')}</span>
              <span className="text-gray-600">→</span>
              <span className={cn(
                'font-mono text-[10px] px-1 rounded',
                String(item.result).includes('high') ? 'bg-red-900/40 text-red-300' :
                String(item.result).includes('medium') ? 'bg-amber-900/40 text-amber-300' :
                String(item.result).includes('low') ? 'bg-emerald-900/40 text-emerald-300' :
                'bg-gray-800 text-gray-300'
              )}>
                {String(item.result || '?')}
              </span>
            </div>
            <div className="text-gray-500 text-[10px] mt-0.5">
              {String(item.input_value || '')}: {String(item.reason || '')}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function JsonTree({ value }: { value: unknown }) {
  const json = formatJson(value)
  return (
    <pre className="text-xs text-gray-300 whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto bg-gray-950 rounded p-2 font-mono">
      {json}
    </pre>
  )
}

function PlainText({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-gray-600 italic">null</span>
  const s = String(value)
  if (s.length <= 80) return <span className="text-gray-200 whitespace-pre-wrap">{s}</span>
  return <span className="text-gray-200 whitespace-pre-wrap">{truncateText(s)}</span>
}

// ─── Master value renderer ──────────────────────────────────────
function ValueDisplay({ hint, value }: { hint: RenderHint; value: unknown }) {
  switch (hint) {
    case 'badge:risk':
      return <RiskBadge level={String(value)} />
    case 'badge:mode':
      return <ModeBadge mode={String(value)} />
    case 'badge:bool':
      return <BoolBadge value={value} />
    case 'table':
      return <TagTable value={value} />
    case 'timeline':
      return <TrailTimeline value={value} />
    case 'json':
      return <JsonTree value={value} />
    case 'text':
    default:
      return <PlainText value={value} />
  }
}

// ─── Single field row ──────────────────────────────────────────
function ControlField({ field, forceExpand }: { field: FieldDef; forceExpand?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const isLongText = typeof field.value === 'string' && field.value.length > 80
  const isComplex = isLongText || (field.hint !== 'text' && field.hint !== 'badge:bool')

  useEffect(() => {
    if (forceExpand !== undefined) setExpanded(forceExpand)
  }, [forceExpand])

  const handleCopy = () => {
    const text = typeof field.value === 'string' ? field.value : formatJson(field.value)
    navigator.clipboard.writeText(text)
  }

  const collapsedPreview = () => {
    if (field.hint === 'badge:risk') return <RiskBadge level={String(field.value)} />
    if (field.hint === 'badge:mode') return <ModeBadge mode={String(field.value)} />
    if (field.hint === 'badge:bool') return <BoolBadge value={field.value} />
    if (field.hint === 'timeline') return <span className="text-gray-500 text-xs">{Array.isArray(field.value) ? `${(field.value as unknown[]).length} 步` : '...'}</span>
    if (field.hint === 'table') {
      const obj = field.value as Record<string, unknown>
      return <span className="text-gray-500 text-xs">{Object.keys(obj || {}).length} 项</span>
    }
    if (typeof field.value === 'string') return <span className="text-gray-500 text-xs">{truncateText(field.value, 60)}</span>
    if (typeof field.value === 'object') return <span className="text-gray-500 text-xs">{'{...}'}</span>
    return <span className="text-gray-500 text-xs">{String(field.value)}</span>
  }

  return (
    <div className="border-b border-gray-800 last:border-b-0 group">
      {/* Collapsed row */}
      <div
        className={cn('flex items-center gap-1 px-3 py-1.5 cursor-pointer hover:bg-gray-800/50 transition-colors', expanded && 'bg-gray-800/30')}
        onClick={() => setExpanded(!expanded)}
      >
        {isComplex
          ? (expanded ? <ChevronDown className="h-3.5 w-3.5 text-gray-500 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-gray-500 shrink-0" />)
          : <span className="w-3.5 shrink-0" />}
        <span className="text-xs font-mono font-semibold text-blue-300 shrink-0">{field.label}</span>
        <span className={cn('text-xs flex-1 min-w-0', expanded && 'hidden')}>
          {collapsedPreview()}
        </span>

        <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100" onClick={e => { e.stopPropagation(); handleCopy() }} title="复制">
          <Copy className="h-3 w-3" />
        </Button>

        <Tooltip>
          <TooltipTrigger asChild>
            <button className="shrink-0 text-gray-600 hover:text-gray-400 transition-colors" onClick={e => e.stopPropagation()} tabIndex={-1}>
              <HelpCircle className="h-3.5 w-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="left" className="max-w-[320px]">
            <p className="text-xs leading-relaxed">{field.help}</p>
            <p className="text-[10px] text-gray-500 mt-1">renderer: {field.hint}</p>
          </TooltipContent>
        </Tooltip>
      </div>

      {/* Expanded value — only for complex types */}
      {expanded && isComplex && (
        <div className="px-6 pb-2 pt-0">
          <ValueDisplay hint={field.hint} value={field.value} />
        </div>
      )}
    </div>
  )
}

// ============================================================
// Main Component
// ============================================================

function CaseLabel({ result }: { result: EntranceResult }) {
  const mode = (result as Record<string, unknown>).response_mode
  if (mode === 'v3') return <span>V3 意图路由</span>
  return <span>case={result.case}</span>
}

interface Props {
  result: EntranceResult
}

export default function ControlInfoPanel({ result }: Props) {
  const [allExpanded, setAllExpanded] = useState(false)
  const fields = extractFields(result)

  // Extract badge-level info for header
  const resultObj = result as Record<string, unknown>
  const responseMode = typeof resultObj.response_mode === 'string' ? resultObj.response_mode : null

  return (
    <div className="mt-2 border border-gray-700 rounded-md overflow-hidden bg-gray-900/50">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-700 bg-gray-900">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-400"><CaseLabel result={result} /></span>
          {responseMode && <ModeBadge mode={responseMode} />}
        </div>
        <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => setAllExpanded(!allExpanded)}>
          {allExpanded ? '全部折叠' : '全部展开'}
        </Button>
      </div>

      {/* Fields — dynamically discovered */}
      <div>
        {fields.map(f => (
          <ControlField key={f.label} field={f} forceExpand={allExpanded} />
        ))}
      </div>
    </div>
  )
}

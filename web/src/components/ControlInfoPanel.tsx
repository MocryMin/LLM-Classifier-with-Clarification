import { useState, useEffect } from 'react'
import { ChevronDown, ChevronRight, Copy, HelpCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { EntranceResult, Case0Data, Case1Data } from '@/types'
import { cn, formatJson, truncateText } from '@/utils'

// ─── Help text registry ───────────────────────────────────────
const HELP: Record<string, string> = {
  case: 'entrance 路由结果。0 = L0 拦截升级人工，1 = L1 意图路由',
  call_body: '调用人工介入接口的请求体（demo 阶段为固定标记）',
  situation_brief: '向人工坐席的情景快速披露，包含用户是谁/发生什么/检测到什么异常',
  user_comfort: '面向用户的安抚话语，以客服"小保"口吻撰写',
  l0_tags: 'L0 五个标签的原始概率值（manual / angry / sad / urgent / non_biz）',
  primary_intent: 'L1 分类的主导意图，包含一级分类、二级分类和置信度',
  top_candidates: '概率大于 0.1 的候选意图列表，按概率降序排列',
  needs_clarification: '是否需要向用户发起澄清，true 时需关注 slots 缺失情况',
  slots: '槽位信息。all_slots=全部待填项，filled_slots=对话中已提取的键值对，missing_slots=尚未填写的槽位名',
  operation: '操作决策类型。clarify_L1=一级分类不明确 / clarify_slots=槽位缺失需收集 / direct_reply=集团直接答复 / route_to_subsidiary=路由子公司 / fallback=未覆盖兜底',
  user_output: '面向用户的输出文本，可能内含 ###tool_call(api_name) 标记',
  reason: '意图路由的判断依据，1-2 句中文说明',
}

// ─── Field definition ─────────────────────────────────────────
interface FieldDef {
  key: string
  label: string
  value: unknown
  help: string
}

function extractFields(result: EntranceResult): FieldDef[] {
  const fields: FieldDef[] = [
    { key: 'case', label: 'case', value: result.case, help: HELP.case },
  ]

  if (result.case === 0) {
    const d = result.data as Case0Data
    fields.push(
      { key: 'call_body', label: 'call_body', value: d.call_body, help: HELP.call_body },
      { key: 'situation_brief', label: 'situation_brief', value: d.situation_brief, help: HELP.situation_brief },
      { key: 'user_comfort', label: 'user_comfort', value: d.user_comfort, help: HELP.user_comfort },
      { key: 'l0_tags', label: 'l0_tags', value: d.l0_tags, help: HELP.l0_tags },
    )
  } else {
    const d = result.data as Case1Data
    fields.push(
      { key: 'primary_intent', label: 'primary_intent', value: d.primary_intent, help: HELP.primary_intent },
      { key: 'top_candidates', label: 'top_candidates', value: d.top_candidates, help: HELP.top_candidates },
      { key: 'needs_clarification', label: 'needs_clarification', value: d.needs_clarification, help: HELP.needs_clarification },
      { key: 'slots', label: 'slots', value: d.slots, help: HELP.slots },
      { key: 'operation', label: 'operation', value: d.operation, help: HELP.operation },
      { key: 'user_output', label: 'user_output', value: d.user_output, help: HELP.user_output },
      { key: 'reason', label: 'reason', value: d.reason, help: HELP.reason },
    )
  }

  return fields
}

// ─── Value renderer ────────────────────────────────────────────
function ValueDisplay({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-gray-600 italic">null</span>
  if (typeof value === 'boolean') return <span className={value ? 'text-emerald-400' : 'text-red-400'}>{String(value)}</span>
  if (typeof value === 'number') return <span className="text-blue-400">{value}</span>
  if (typeof value === 'string') {
    if (value.length <= 80) return <span className="text-gray-200 whitespace-pre-wrap">{value}</span>
    return <span className="text-gray-200 whitespace-pre-wrap">{truncateText(value)}</span>
  }
  // Object/array → formatted JSON
  const json = formatJson(value)
  return <pre className="text-xs text-gray-300 whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto bg-gray-950 rounded p-2">{json}</pre>
}

// ─── Single field row ──────────────────────────────────────────
function ControlField({ field, forceExpand }: { field: FieldDef; forceExpand?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const isComplex = typeof field.value === 'object' || (typeof field.value === 'string' && field.value.length > 80)

  useEffect(() => {
    if (forceExpand !== undefined) setExpanded(forceExpand);
  }, [forceExpand]);

  const handleCopy = () => {
    const text = typeof field.value === 'string' ? field.value : formatJson(field.value)
    navigator.clipboard.writeText(text)
  }

  return (
    <div className="border-b border-gray-800 last:border-b-0 group">
      {/* Collapsed row */}
      <div
        className={cn('flex items-center gap-1 px-3 py-1.5 cursor-pointer hover:bg-gray-800/50 transition-colors', expanded && 'bg-gray-800/30')}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5 text-gray-500 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-gray-500 shrink-0" />}
        <span className="text-xs font-mono font-semibold text-blue-300 shrink-0">{field.label}</span>
        <span className={cn('text-xs text-gray-500 truncate flex-1', expanded && 'hidden')}>
          {typeof field.value === 'string' ? truncateText(field.value, 60) : typeof field.value === 'object' ? '{...}' : String(field.value)}
        </span>

        {/* Copy button */}
        <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100" onClick={e => { e.stopPropagation(); handleCopy(); }} title="复制">
          <Copy className="h-3 w-3" />
        </Button>

        {/* Help tooltip */}
        <Tooltip>
          <TooltipTrigger asChild>
            <button className="shrink-0 text-gray-600 hover:text-gray-400 transition-colors" onClick={e => e.stopPropagation()} tabIndex={-1}>
              <HelpCircle className="h-3.5 w-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="left" className="max-w-[280px]">
            <p className="text-xs leading-relaxed">{field.help}</p>
          </TooltipContent>
        </Tooltip>
      </div>

      {/* Expanded value */}
      {expanded && (
        <div className="px-6 pb-2 pt-0">
          <ValueDisplay value={field.value} />
        </div>
      )}
    </div>
  )
}

// ─── Main component ────────────────────────────────────────────
interface Props {
  result: EntranceResult
}

export default function ControlInfoPanel({ result }: Props) {
  const [allExpanded, setAllExpanded] = useState(false)
  const fields = extractFields(result)

  return (
    <div className="mt-2 border border-gray-700 rounded-md overflow-hidden bg-gray-900/50">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-700 bg-gray-900">
        <span className="text-xs font-medium text-gray-400">控制信息 ({result.case === 0 ? 'L0 拦截升级' : 'L1 意图路由'})</span>
        <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => setAllExpanded(!allExpanded)}>
          {allExpanded ? '全部折叠' : '全部展开'}
        </Button>
      </div>

      {/* Fields */}
      <div>
        {fields.map(f => (
          <ControlField key={f.key} field={f} forceExpand={allExpanded} />
        ))}
      </div>
    </div>
  )
}

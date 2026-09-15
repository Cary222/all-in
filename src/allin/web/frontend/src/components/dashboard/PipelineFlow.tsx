import { Bot, CheckCircle, Eye, MessageSquare, Search, Send } from 'lucide-react'

const steps = [
  { icon: Search, label: '采集', desc: '搜索岗位' },
  { icon: Bot, label: 'AI 评分', desc: '匹配打分' },
  { icon: MessageSquare, label: '招呼语', desc: '生成内容' },
  { icon: CheckCircle, label: '人工确认', desc: '审核选择' },
  { icon: Send, label: '发送', desc: '安全队列' },
  { icon: Eye, label: '监测', desc: '跟进回复' },
]

export function PipelineFlow() {
  return (
    <div className="rounded-xl border border-card-border bg-card">
      <div className="border-b border-card-border px-4 py-3">
        <h3 className="text-sm font-semibold text-foreground">自动求职流程</h3>
        <p className="mt-1 text-xs text-muted">投递前始终保留人工确认节点</p>
      </div>
      <ol className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
        {steps.map((step, index) => (
          <li key={step.label} className="relative border-b border-r border-card-border p-4 last:border-r-0 lg:border-b-0">
            <div className="flex items-center gap-3 lg:block">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted-surface text-primary">
                <step.icon className="h-4 w-4" strokeWidth={1.8} />
              </div>
              <div className="min-w-0 lg:mt-3">
                <div className="text-xs font-semibold text-foreground">{step.label}</div>
                <div className="mt-0.5 text-[10px] text-muted">{step.desc}</div>
              </div>
            </div>
            <span className="absolute right-2 top-2 font-mono text-[9px] text-muted/60">{String(index + 1).padStart(2, '0')}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

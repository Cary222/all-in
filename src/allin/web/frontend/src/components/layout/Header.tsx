import { useLocation } from 'react-router-dom'
import { Activity } from 'lucide-react'

const pageMeta: Record<string, { title: string; description: string }> = {
  '/': {
    title: '工作台',
    description: '处理今天最需要推进的求职任务',
  },
  '/jobs': {
    title: '岗位池',
    description: '筛选、审阅并管理已采集岗位',
  },
  '/monitor': {
    title: '监测执行',
    description: '跟进投递状态与招聘者回复',
  },
  '/config': {
    title: '配置',
    description: '管理求职偏好、平台能力与自动化边界',
  },
}

export function Header() {
  const location = useLocation()
  const meta = pageMeta[location.pathname] || { title: 'All In', description: '本地智能求职控制台' }

  return (
    <header className="flex min-h-16 shrink-0 items-center justify-between border-b border-card-border bg-card px-4 md:px-6">
      <div className="min-w-0 py-3">
        <h1 className="truncate text-lg font-semibold tracking-[-0.02em] text-foreground">{meta.title}</h1>
        <p className="mt-0.5 hidden truncate text-xs text-muted sm:block">{meta.description}</p>
      </div>
      <div
        className="flex shrink-0 items-center gap-2 rounded-md border border-card-border bg-muted-surface px-2.5 py-1.5 text-xs font-medium text-muted"
        aria-label="当前为本地控制台模式"
      >
        <Activity className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
        <span className="hidden sm:inline">本地模式</span>
      </div>
    </header>
  )
}

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { HistoryItem } from '@/hooks/useDashboard'

interface RecentActivityProps {
  data: HistoryItem[]
}

const ACTION_LABELS: Record<string, string> = {
  scrape: '采集',
  scored: '评分',
  sent: '发送',
  manual_sent: '手动发送',
  replied: '回复',
  hr_reply_detected: 'HR 消息',
  auto_replied: '自动回复',
  error: '错误',
  approved: '确认',
  filtered: '过滤',
  resume_sent: '简历',
}

function formatTime(dateStr: string) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return `${(date.getMonth() + 1).toString().padStart(2, '0')}-${date.getDate().toString().padStart(2, '0')} ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

export function RecentActivity({ data }: RecentActivityProps) {
  return (
    <Card>
      <CardHeader className="border-b border-card-border">
        <CardTitle>最近活动</CardTitle>
        <p className="mt-1 text-xs text-muted">最近三条岗位处理记录</p>
      </CardHeader>
      <CardContent className="p-0">
        {data.length ? (
          <div className="divide-y divide-card-border">
            {data.slice(0, 3).map(item => (
              <article key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
                <Badge variant={item.action as any}>{ACTION_LABELS[item.action] || item.action}</Badge>
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">{item.company} · {item.title}</span>
                <time className="shrink-0 font-mono text-[11px] text-muted" dateTime={item.created_at}>{formatTime(item.created_at)}</time>
              </article>
            ))}
          </div>
        ) : (
          <p className="px-4 py-6 text-sm text-muted">暂无活动记录。完成采集或评分后会显示在这里。</p>
        )}
      </CardContent>
    </Card>
  )
}

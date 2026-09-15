import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { TopCompany } from '@/hooks/useDashboard'

interface TopCompaniesProps {
  data: TopCompany[]
}

export function TopCompanies({ data }: TopCompaniesProps) {
  if (!data.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>高分公司</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-6 text-muted">完成岗位采集和 AI 评分后，这里会显示平均分最高的公司。</p>
        </CardContent>
      </Card>
    )
  }

  const maxScore = Math.max(...data.map(item => item.avg_score))

  return (
    <Card>
      <CardHeader className="border-b border-card-border">
        <CardTitle>高分公司</CardTitle>
        <p className="mt-1 text-xs text-muted">按平均匹配评分排序</p>
      </CardHeader>
      <CardContent className="p-0">
        <ol className="divide-y divide-card-border">
          {data.map((company, index) => (
            <li key={`${company.company}-${index}`} className="flex items-center gap-3 px-4 py-3">
              <span className="w-5 shrink-0 font-mono text-xs text-muted">{String(index + 1).padStart(2, '0')}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate text-sm font-medium text-foreground">{company.company}</span>
                  <span className="font-mono text-sm font-semibold tabular-nums text-primary">{company.avg_score}</span>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <div className="h-1 flex-1 overflow-hidden rounded-sm bg-muted-surface" aria-hidden="true">
                    <div className="h-full rounded-sm bg-primary" style={{ width: `${(company.avg_score / maxScore) * 100}%` }} />
                  </div>
                  <span className="shrink-0 text-[11px] text-muted">{company.job_count} 岗</span>
                </div>
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}

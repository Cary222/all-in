import { Fragment, useEffect, useState } from 'react'
import { CheckCircle2, ChevronDown, ChevronUp, ExternalLink, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { getStatusLabel } from '@/lib/status'
import { PLATFORM_SHORT_LABELS } from '@/lib/platforms'
import type { Job } from '@/hooks/useDashboard'
import type { JobSortKey, JobSortOrder } from '@/hooks/useJobSearch'

interface JobsTableProps {
  jobs: Job[]
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  selectedIds: string[]
  onToggleSelected: (id: string) => void
  onSoftDelete?: (job: Job) => void
  onMarkManuallySent?: (job: Job) => void
  loading?: boolean
  sortBy: JobSortKey
  sortOrder: JobSortOrder
  onSortChange: (sortBy: JobSortKey) => void
}

const sortOptions: Array<{ value: JobSortKey; label: string }> = [
  { value: 'created_at', label: '采集时间' },
  { value: 'score', label: '匹配评分' },
  { value: 'salary', label: '薪资' },
  { value: 'education', label: '学历要求' },
  { value: 'status', label: '岗位状态' },
  { value: 'hr_active', label: '招聘者活跃度' },
]

function safeJobUrl(job: Job): string | null {
  const platform = job.source_platform || 'boss'
  if (platform !== 'boss' && platform !== 'zhilian' && platform !== '51job' && platform !== 'liepin') return null
  try {
    const parsed = platform === 'boss'
      ? new URL(job.url || '', 'https://www.zhipin.com')
      : new URL(job.url || '')
    if (parsed.protocol !== 'https:') return null
    const rootDomain = platform === 'boss'
      ? 'zhipin.com'
      : platform === 'zhilian'
        ? 'zhaopin.com'
        : platform === '51job'
          ? '51job.com'
          : 'liepin.com'
    if (parsed.hostname !== rootDomain && !parsed.hostname.endsWith(`.${rootDomain}`)) return null
    return parsed.toString()
  } catch {
    return null
  }
}

function statusVariant(status: string) {
  const variants = new Set([
    'pending',
    'scored',
    'filtered',
    'ready',
    'approved',
    'skipped',
    'sent',
    'replied',
    'resume_sent',
    'needs_resume',
    'follow_up_sent',
    'rejected',
    'error',
  ])
  return variants.has(status) ? status : 'default'
}

function recruitmentTypeLabel(job: Job) {
  if (job.recruitment_type === 'campus') return '校招'
  if (job.recruitment_type === 'experienced') return '社招'
  return '类型未识别'
}

function normalizeDate(dateStr: string) {
  return /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(dateStr)
    ? `${dateStr.replace(' ', 'T')}Z`
    : dateStr
}

function timeAgo(dateStr: string) {
  if (!dateStr) return ''
  const timestamp = new Date(normalizeDate(dateStr)).getTime()
  if (Number.isNaN(timestamp)) return ''
  const diff = Date.now() - timestamp
  const hours = Math.floor(diff / 3600000)
  if (hours < 1) return '刚刚'
  if (hours < 24) return `${hours}h 前`
  return `${Math.floor(hours / 24)}d 前`
}

function scoreClass(score: number) {
  if (score >= 80) return 'text-success'
  if (score >= 60) return 'text-primary'
  return 'text-muted'
}

function JobDetails({ job }: { job: Job }) {
  const details = [
    { label: 'JD 摘要', content: job.jd || '无' },
    { label: '招呼语', content: job.greeting || '未生成' },
    { label: '评分理由', content: job.score_reason || '无' },
  ]

  return (
    <div className="grid grid-cols-1 gap-3 text-sm lg:grid-cols-3">
      {details.map(detail => (
        <section key={detail.label} className="rounded-[10px] border border-card-border bg-card p-4">
          <h4 className="mb-2 text-xs font-semibold text-foreground">{detail.label}</h4>
          <p className="line-clamp-6 whitespace-pre-wrap leading-6 text-muted">{detail.content}</p>
        </section>
      ))}
    </div>
  )
}

export function JobsTable({ jobs, page, pageSize, total, onPageChange, selectedIds, onToggleSelected, onSoftDelete, onMarkManuallySent, loading = false, sortBy, sortOrder, onSortChange }: JobsTableProps) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [pageInput, setPageInput] = useState(String(page + 1))
  const totalPages = Math.ceil(total / pageSize)
  const hasActions = Boolean(onSoftDelete || onMarkManuallySent)

  useEffect(() => {
    setPageInput(String(page + 1))
  }, [page])

  const jumpToPage = () => {
    const requested = Number.parseInt(pageInput, 10)
    if (!Number.isFinite(requested) || totalPages < 1) {
      setPageInput(String(page + 1))
      return
    }
    onPageChange(Math.min(totalPages - 1, Math.max(0, requested - 1)))
  }

  const renderActions = (job: Job) => {
    const jobUrl = safeJobUrl(job)
    const isExternalPlatform = job.source_platform === 'zhilian' || job.source_platform === '51job' || job.source_platform === 'liepin'
    const alreadySent = ['sent', 'replied', 'resume_sent', 'needs_resume', 'follow_up_sent'].includes(job.status)

    return (
      <div className="flex flex-wrap items-center gap-1.5">
        {jobUrl ? (
          <a
            href={jobUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-8 items-center gap-1 rounded-md border border-card-border bg-card px-2.5 text-[11px] font-medium text-foreground transition-colors hover:border-primary/40 hover:text-primary"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            查看岗位
          </a>
        ) : (
          <span className="inline-flex h-8 items-center rounded-md bg-status-warning px-2.5 text-[11px] font-medium text-status-warning-foreground">链接不可用</span>
        )}
        {isExternalPlatform && onMarkManuallySent && (
          <button
            type="button"
            disabled={alreadySent}
            onClick={() => onMarkManuallySent(job)}
            className="inline-flex h-8 items-center gap-1 rounded-md bg-primary px-2.5 text-[11px] font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:bg-status-success disabled:text-status-success-foreground"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            {alreadySent ? '已发送' : '我已发送'}
          </button>
        )}
        {onSoftDelete && (
          <button
            type="button"
            onClick={() => onSoftDelete(job)}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition-colors hover:bg-status-danger hover:text-status-danger-foreground"
            aria-label={`将 ${job.company} ${job.title} 移入回收站`}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>
    )
  }

  return (
    <Card>
      <CardHeader className="gap-3 border-b border-card-border sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle>岗位列表</CardTitle>
          <p className="mt-1 text-xs text-muted">{total} 条记录，点击岗位查看摘要与评分依据</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="shrink-0 text-xs text-muted">排序</span>
          <Select
            value={sortBy}
            onChange={event => onSortChange(event.target.value as JobSortKey)}
            className="h-8 min-w-[118px] py-1 text-xs"
            aria-label="岗位排序字段"
          >
            {sortOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </Select>
          <Button variant="secondary" size="sm" className="h-8 px-2.5 text-xs" onClick={() => onSortChange(sortBy)}>
            {sortOrder === 'asc' ? '升序' : '降序'}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="space-y-2 p-3 md:hidden">
          {jobs.map(job => {
            const isExpanded = expanded === job.id
            return (
              <article key={job.id} className="rounded-[10px] border border-card-border bg-card">
                <div className="p-3">
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(job.id)}
                      onChange={() => onToggleSelected(job.id)}
                      aria-label={`选择 ${job.company} ${job.title}`}
                      className="mt-1 h-4 w-4 shrink-0 accent-primary"
                    />
                    <button type="button" onClick={() => setExpanded(isExpanded ? null : job.id)} className="min-w-0 flex-1 text-left">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <h3 className="truncate text-sm font-semibold text-foreground">{job.title}</h3>
                          <p className="mt-0.5 truncate text-xs text-muted">{job.company}</p>
                        </div>
                        {isExpanded ? <ChevronUp className="mt-0.5 h-4 w-4 shrink-0 text-muted" /> : <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-muted" />}
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                        <span className="rounded-md bg-muted-surface px-1.5 py-0.5 font-medium text-foreground">{PLATFORM_SHORT_LABELS[job.source_platform || 'boss'] || 'BOSS'}</span>
                        <span>{job.city || '城市未识别'}</span>
                        <span aria-hidden="true">·</span>
                        <span>{job.salary || '薪资未识别'}</span>
                        <span aria-hidden="true">·</span>
                        <span>{job.education || '学历未识别'}</span>
                      </div>
                    </button>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-3 border-t border-card-border pt-3">
                    <div className="flex items-center gap-2">
                      <span className={`font-mono text-base font-semibold tabular-nums ${scoreClass(job.score)}`}>{job.score || '-'}</span>
                      <Badge variant={statusVariant(job.status) as any}>{getStatusLabel(job.status)}</Badge>
                    </div>
                    <span className="text-[11px] text-muted">{timeAgo(job.created_at)}</span>
                  </div>
                  {hasActions && <div className="mt-3">{renderActions(job)}</div>}
                </div>
                {isExpanded && <div className="border-t border-card-border bg-muted-surface p-3"><JobDetails job={job} /></div>}
              </article>
            )
          })}
          {!jobs.length && (
            <div className="px-4 py-10 text-center text-sm text-muted">
              {loading ? '正在读取岗位…' : '没有符合当前条件的岗位'}
            </div>
          )}
        </div>

        <div className="hidden overflow-x-auto md:block">
          <table className="w-full min-w-[920px] text-sm">
            <thead>
              <tr className="border-b border-card-border bg-muted-surface text-xs text-muted">
                <th className="w-10 px-3 py-3 text-center font-medium">选</th>
                <th className="px-4 py-3 text-left font-medium">岗位</th>
                <th className="px-4 py-3 text-left font-medium">地点与要求</th>
                <th className="w-20 px-4 py-3 text-left font-medium">评分</th>
                <th className="px-4 py-3 text-left font-medium">状态</th>
                <th className="px-4 py-3 text-left font-medium">最近动态</th>
                {hasActions && <th className="min-w-[210px] px-3 py-3 text-left font-medium">操作</th>}
              </tr>
            </thead>
            <tbody>
              {jobs.map(job => {
                const isExpanded = expanded === job.id
                return (
                  <Fragment key={job.id}>
                    <tr className="cursor-pointer border-b border-card-border transition-colors hover:bg-muted-surface" onClick={() => setExpanded(isExpanded ? null : job.id)}>
                      <td className="px-3 py-3 text-center" onClick={event => event.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(job.id)}
                          onChange={() => onToggleSelected(job.id)}
                          aria-label={`选择 ${job.company} ${job.title}`}
                          className="h-4 w-4 accent-primary"
                        />
                      </td>
                      <td className="max-w-[280px] px-4 py-3">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="truncate font-semibold text-foreground">{job.title}</span>
                          <span className="shrink-0 rounded-md bg-muted-surface px-1.5 py-0.5 text-[10px] font-medium text-foreground">{PLATFORM_SHORT_LABELS[job.source_platform || 'boss'] || 'BOSS'}</span>
                        </div>
                        <div className="mt-1 flex min-w-0 items-center gap-2 text-xs text-muted">
                          <span className="truncate">{job.company}</span>
                          {job.company_size && <span className="shrink-0">{job.company_size}</span>}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-foreground">{job.salary || '薪资未识别'} · {job.city || '城市未识别'}</div>
                        <div className="mt-1 text-xs text-muted">{job.education || '学历未识别'} · {recruitmentTypeLabel(job)}</div>
                      </td>
                      <td className="px-4 py-3"><span className={`font-mono text-base font-semibold tabular-nums ${scoreClass(job.score)}`}>{job.score || '-'}</span></td>
                      <td className="px-4 py-3">
                        <Badge variant={statusVariant(job.status) as any}>{getStatusLabel(job.status)}</Badge>
                        <div className="mt-1.5 text-[11px] text-muted">{job.hr_active || '活跃度未知'}</div>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted">
                        <div className="flex items-center gap-2">
                          <span>{timeAgo(job.created_at)}</span>
                          {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                        </div>
                      </td>
                      {hasActions && <td className="px-3 py-3" onClick={event => event.stopPropagation()}>{renderActions(job)}</td>}
                    </tr>
                    {isExpanded && (
                      <tr className="border-b border-card-border bg-muted-surface">
                        <td colSpan={hasActions ? 7 : 6} className="px-6 py-4"><JobDetails job={job} /></td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
              {!jobs.length && (
                <tr>
                  <td colSpan={hasActions ? 7 : 6} className="px-4 py-10 text-center text-sm text-muted">
                    {loading ? '正在读取岗位…' : '没有符合当前条件的岗位'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {totalPages > 0 && (
          <div className="flex flex-wrap items-center justify-center gap-3 border-t border-card-border px-4 py-3 text-xs">
            <button onClick={() => onPageChange(0)} disabled={page === 0} className="font-medium text-muted transition-colors hover:text-foreground disabled:opacity-30">首页</button>
            <button onClick={() => onPageChange(Math.max(0, page - 1))} disabled={page === 0} className="font-medium text-muted transition-colors hover:text-foreground disabled:opacity-30">上一页</button>
            <label className="flex items-center gap-1 text-muted">
              第
              <input
                type="number"
                min={1}
                max={Math.max(1, totalPages)}
                value={pageInput}
                onChange={event => setPageInput(event.target.value)}
                onKeyDown={event => { if (event.key === 'Enter') jumpToPage() }}
                onBlur={jumpToPage}
                aria-label="跳转页码"
                className="w-14 rounded-md border border-card-border bg-card px-2 py-1 text-center font-mono text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-ring"
              />
              页 / {totalPages} 页
            </label>
            <button onClick={() => onPageChange(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1} className="font-medium text-muted transition-colors hover:text-foreground disabled:opacity-30">下一页</button>
            <button onClick={() => onPageChange(totalPages - 1)} disabled={page >= totalPages - 1} className="font-medium text-muted transition-colors hover:text-foreground disabled:opacity-30">尾页</button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

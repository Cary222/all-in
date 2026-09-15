import { useState } from 'react'
import { ChevronDown, ChevronUp, RotateCcw, Search, SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { STATUS_LABELS } from '@/lib/status'
import { hasActiveJobFilters, type JobFilters } from '@/lib/jobFilters'

interface JobFilterBarProps {
  filters: JobFilters
  onChange: (filters: JobFilters) => void
  onReset: () => void
  resultCount: number
  totalCount: number
  invalidSalary?: boolean
  showStatus?: boolean
  showSource?: boolean
  compact?: boolean
}

export function JobFilterBar({
  filters,
  onChange,
  onReset,
  resultCount,
  totalCount,
  invalidSalary = false,
  showStatus = false,
  showSource = false,
  compact = false,
}: JobFilterBarProps) {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const controlClass = cn('min-w-0', compact && 'h-7 px-2 text-xs')
  const update = (key: keyof JobFilters, value: string) => onChange({ ...filters, [key]: value })
  const advancedActive = Boolean(filters.minScore || filters.salaryMin || filters.salaryMax || filters.education || filters.recruitmentType)

  const searchInput = (
    <label className="relative min-w-0">
      <Search className={cn('pointer-events-none absolute text-muted', compact ? 'left-2 top-2 h-3 w-3' : 'left-3 top-2.5 h-4 w-4')} />
      <Input
        value={filters.query}
        onChange={event => update('query', event.target.value)}
        placeholder="搜索职位、公司、JD 或评分理由"
        className={cn(controlClass, compact ? 'pl-7' : 'pl-9')}
        aria-label="关键词"
      />
    </label>
  )

  if (compact) {
    return (
      <div className="grid min-w-0 grid-cols-2 gap-1.5 xl:grid-cols-4">
        <div className="col-span-2 xl:col-span-1">{searchInput}</div>
        <Select className={controlClass} value={filters.createdWithin} onChange={event => update('createdWithin', event.target.value)} aria-label="采集时间">
          <option value="">采集时间：全部</option>
          <option value="today">今天</option>
          <option value="3d">近 3 天</option>
          <option value="7d">近 7 天</option>
        </Select>
        <Select className={controlClass} value={filters.minScore} onChange={event => update('minScore', event.target.value)} aria-label="最低评分">
          <option value="">最低评分：不限</option>
          <option value="60">60+</option>
          <option value="71">71+</option>
          <option value="80">80+</option>
        </Select>
        <Input type="number" min="0" step="1" value={filters.salaryMin} onChange={event => update('salaryMin', event.target.value)} placeholder="最低薪资 K" className={controlClass} aria-label="最低薪资 K" />
        <Input type="number" min="0" step="1" value={filters.salaryMax} onChange={event => update('salaryMax', event.target.value)} placeholder="最高薪资 K" className={controlClass} aria-label="最高薪资 K" />
        <Select className={controlClass} value={filters.education} onChange={event => update('education', event.target.value)} aria-label="学历要求">
          <option value="">学历：全部</option>
          <option value="博士">博士</option>
          <option value="硕士">硕士</option>
          <option value="本科">本科</option>
          <option value="大专">大专</option>
          <option value="不限">学历不限</option>
          <option value="unknown">未识别</option>
        </Select>
        <Select className={controlClass} value={filters.recruitmentType} onChange={event => update('recruitmentType', event.target.value)} aria-label="招聘类型">
          <option value="">招聘类型：全部</option>
          <option value="campus">校招</option>
          <option value="experienced">社招</option>
          <option value="unknown">未识别</option>
        </Select>
        <div className="col-span-2 flex min-w-0 items-center justify-end xl:col-span-1">
          <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs" disabled={!hasActiveJobFilters(filters)} onClick={onReset}>
            <RotateCcw className="mr-1 h-3 w-3" />重置筛选
          </Button>
        </div>
        {invalidSalary && <p className="col-span-full text-xs font-medium text-danger">最低薪资不能高于最高薪资，请调整后再筛选。</p>}
      </div>
    )
  }

  return (
    <section className="mb-4 rounded-[10px] border border-card-border bg-muted-surface p-3" aria-label="岗位筛选">
      <div className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-[minmax(260px,1fr)_160px_160px_auto]">
        {searchInput}
        {showSource ? (
          <Select className={controlClass} value={filters.sourcePlatform} onChange={event => update('sourcePlatform', event.target.value)} aria-label="来源平台">
            <option value="">来源平台：全部</option>
            <option value="boss">BOSS 直聘</option>
            <option value="zhilian">智联招聘</option>
            <option value="51job">前程无忧</option>
            <option value="liepin">猎聘</option>
          </Select>
        ) : (
          <Select className={controlClass} value={filters.createdWithin} onChange={event => update('createdWithin', event.target.value)} aria-label="采集时间">
            <option value="">采集时间：全部</option>
            <option value="today">今天</option>
            <option value="3d">近 3 天</option>
            <option value="7d">近 7 天</option>
          </Select>
        )}
        {showStatus ? (
          <Select className={controlClass} value={filters.status} onChange={event => update('status', event.target.value)} aria-label="岗位状态">
            <option value="">全部状态</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </Select>
        ) : (
          <Select className={controlClass} value={filters.minScore} onChange={event => update('minScore', event.target.value)} aria-label="最低评分">
            <option value="">最低评分：不限</option>
            <option value="60">60+</option>
            <option value="71">71+</option>
            <option value="80">80+</option>
          </Select>
        )}
        <Button type="button" variant="secondary" size="sm" className="h-9 justify-center px-3" onClick={() => setShowAdvanced(value => !value)} aria-expanded={showAdvanced}>
          <SlidersHorizontal className="mr-1.5 h-3.5 w-3.5" />
          更多筛选{advancedActive ? ' · 已启用' : ''}
          {showAdvanced ? <ChevronUp className="ml-1.5 h-3.5 w-3.5" /> : <ChevronDown className="ml-1.5 h-3.5 w-3.5" />}
        </Button>
      </div>

      {showAdvanced && (
        <div className="mt-3 grid grid-cols-1 gap-2 border-t border-card-border pt-3 sm:grid-cols-2 xl:grid-cols-6">
          {showSource && (
            <Select className={controlClass} value={filters.createdWithin} onChange={event => update('createdWithin', event.target.value)} aria-label="采集时间">
              <option value="">采集时间：全部</option>
              <option value="today">今天</option>
              <option value="3d">近 3 天</option>
              <option value="7d">近 7 天</option>
            </Select>
          )}
          {showStatus && (
            <Select className={controlClass} value={filters.minScore} onChange={event => update('minScore', event.target.value)} aria-label="最低评分">
              <option value="">最低评分：不限</option>
              <option value="60">60+</option>
              <option value="71">71+</option>
              <option value="80">80+</option>
            </Select>
          )}
          <Input type="number" min="0" step="1" value={filters.salaryMin} onChange={event => update('salaryMin', event.target.value)} placeholder="最低薪资 K" className={controlClass} aria-label="最低薪资 K" />
          <Input type="number" min="0" step="1" value={filters.salaryMax} onChange={event => update('salaryMax', event.target.value)} placeholder="最高薪资 K" className={controlClass} aria-label="最高薪资 K" />
          <Select className={controlClass} value={filters.education} onChange={event => update('education', event.target.value)} aria-label="学历要求">
            <option value="">学历：全部</option>
            <option value="博士">博士</option>
            <option value="硕士">硕士</option>
            <option value="本科">本科</option>
            <option value="大专">大专</option>
            <option value="不限">学历不限</option>
            <option value="unknown">未识别</option>
          </Select>
          <Select className={controlClass} value={filters.recruitmentType} onChange={event => update('recruitmentType', event.target.value)} aria-label="招聘类型">
            <option value="">招聘类型：全部</option>
            <option value="campus">校招</option>
            <option value="experienced">社招</option>
            <option value="unknown">未识别</option>
          </Select>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-card-border pt-3">
        <span className="text-xs text-muted">显示 <span className="font-mono font-semibold tabular-nums text-foreground">{resultCount}</span> 条，共 {totalCount} 条</span>
        <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs" disabled={!hasActiveJobFilters(filters)} onClick={onReset}>
          <RotateCcw className="mr-1 h-3 w-3" />重置筛选
        </Button>
      </div>
      {invalidSalary && <p className="mt-2 text-xs font-medium text-danger">最低薪资不能高于最高薪资，请调整后再筛选。</p>}
    </section>
  )
}

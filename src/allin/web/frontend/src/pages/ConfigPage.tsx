import { useConfig } from '@/hooks/useConfig'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import { TagsInput } from '@/components/ui/tags-input'
import { CityMultiSelect, type CityOption } from '@/components/config/CityMultiSelect'
import { ResumeUploadSection } from '@/components/config/ResumeUploadSection'
import { Save, RotateCcw, Loader2, Lock, Unlock, RefreshCw, AlertTriangle, CheckCircle2, Clock } from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import { PLATFORM_LABELS, PLATFORM_SHORT_LABELS } from '@/lib/platforms'

const AI_SERVICES = {
  anthropic: {
    label: 'Claude / Anthropic',
    provider: 'anthropic',
    baseUrl: '',
    defaultModel: 'claude-sonnet-4-6',
    keyEnv: 'ANTHROPIC_API_KEY',
  },
  deepseek: {
    label: 'DeepSeek',
    provider: 'openai_compatible',
    baseUrl: 'https://api.deepseek.com',
    defaultModel: '',
    keyEnv: 'DEEPSEEK_API_KEY',
  },
  doubao: {
    label: '豆包 / 火山方舟',
    provider: 'openai_compatible',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    defaultModel: '',
    keyEnv: 'ARK_API_KEY',
  },
  custom: {
    label: '其他 OpenAI 兼容接口',
    provider: 'openai_compatible',
    baseUrl: '',
    defaultModel: '',
    keyEnv: 'OPENAI_API_KEY',
  },
} as const

type AiService = keyof typeof AI_SERVICES
type PlatformId = 'boss' | 'zhilian' | '51job' | 'liepin'
type ConfigArea = 'profile' | 'sources' | 'automation' | 'safety'
type SafetyArea = 'risk_control' | 'delivery' | 'monitor' | 'follow_up' | 'data'

// 与后端 allin/collection/checkpoint.py 保持一致；0 表示停用断点，每次完整重搜。
const DEFAULT_RESUME_TTL_HOURS = 24
const MAX_RESUME_TTL_HOURS = 720

const CONFIG_AREAS: Array<{ key: ConfigArea; label: string; description: string }> = [
  { key: 'profile', label: '求职偏好', description: '简历、目标岗位和筛选底线' },
  { key: 'sources', label: '岗位来源', description: '平台、关键词、城市和采集顺序' },
  { key: 'automation', label: 'AI 与自动化', description: '模型连接、评分和招呼语策略' },
  { key: 'safety', label: '安全与跟进', description: '发送限制、HR 监测和数据记录' },
]

const SAFETY_AREAS: Array<{ key: SafetyArea; label: string }> = [
  { key: 'risk_control', label: '平台风控与冷却' },
  { key: 'delivery', label: '发送安全' },
  { key: 'monitor', label: 'HR 监测' },
  { key: 'follow_up', label: '自动跟进' },
  { key: 'data', label: '数据记录' },
]

const LEGACY_SECTION_MAP: Record<string, { area: ConfigArea; safety?: SafetyArea }> = {
  profile: { area: 'profile' },
  search: { area: 'sources' },
  scoring: { area: 'automation' },
  ai: { area: 'automation' },
  safety: { area: 'safety', safety: 'risk_control' },
  collection: { area: 'safety', safety: 'delivery' },
  throttle: { area: 'safety', safety: 'delivery' },
  monitor: { area: 'safety', safety: 'monitor' },
  follow_up: { area: 'safety', safety: 'follow_up' },
  dedup: { area: 'safety', safety: 'data' },
}

const BOSS_FILTER_OPTIONS = {
  job_type: ['全职', '兼职', '实习'],
  experience: ['经验不限', '应届生', '1年以内', '1-3年', '3-5年', '5-10年', '10年以上', '在校生'],
  degree: ['学历不限', '大专', '本科', '硕士', '博士', '高中', '中专/中技', '初中及以下'],
  scale: ['0-20人', '20-99人', '100-499人', '500-999人', '1000-9999人', '10000人以上'],
  salary: ['3K以下', '3-5K', '5-10K', '10-20K', '20-50K', '50K以上'],
} as const

export default function ConfigPage() {
  const { config, schema, loading, saving, dirty, error, message, updateConfig, saveConfig, resetConfig } = useConfig()
  const requestedSection = new URLSearchParams(window.location.search).get('section') || ''
  const requestedArea = LEGACY_SECTION_MAP[requestedSection]
  const [activeArea, setActiveArea] = useState<ConfigArea>(requestedArea?.area || 'profile')
  const [activePlatform, setActivePlatform] = useState<PlatformId>('boss')
  const [activeSafetyArea, setActiveSafetyArea] = useState<SafetyArea>(requestedArea?.safety || 'delivery')
  const [aiTest, setAiTest] = useState<{ testing: boolean; ok?: boolean; message?: string }>({ testing: false })
  const [modelList, setModelList] = useState<{ loading: boolean; models: string[]; message?: string; error?: boolean }>({ loading: false, models: [] })
  const modelRequest = useRef<AbortController | null>(null)
  const [cityOptions, setCityOptions] = useState<CityOption[]>([])
  const [zhilianCityOptions, setZhilianCityOptions] = useState<CityOption[]>([])
  const [job51CityOptions, setJob51CityOptions] = useState<CityOption[]>([])
  const [liepinCityOptions, setLiepinCityOptions] = useState<CityOption[]>([])
  const [cityRefreshing, setCityRefreshing] = useState(false)
  const [cityMessage, setCityMessage] = useState('')

  useEffect(() => {
    setModelList({ loading: false, models: [] })
    return () => modelRequest.current?.abort()
  }, [config?.ai?.service, config?.ai?.provider, config?.ai?.base_url, config?.ai?.api_key, config?.ai?.api_key_masked, config?.ai?.auth_token_masked, config?.ai?.clear_credentials])

  const handleFetchModels = async () => {
    modelRequest.current?.abort()
    const controller = new AbortController()
    modelRequest.current = controller
    setModelList({ loading: true, models: [] })
    try {
      const res = await fetch('/api/config/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ai: config?.ai || {} }),
        signal: controller.signal,
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || '获取模型列表失败')
      if (!Array.isArray(data.models) || !data.models.every((model: unknown) => typeof model === 'string')) {
        throw new Error('模型列表格式不正确，可手动填写模型 ID')
      }
      if (!controller.signal.aborted) setModelList({
        loading: false,
        models: data.models,
        message: data.models.length ? `已获取 ${data.models.length} 个模型，请选择或继续手动填写。` : '服务商未返回可用模型，可手动填写模型 ID。',
      })
    } catch (error) {
      if (!controller.signal.aborted) setModelList({ loading: false, models: [], error: true, message: error instanceof Error ? error.message : '获取模型列表失败，请重试' })
    }
  }

  useEffect(() => {
    fetch('/api/cities', { cache: 'no-store' })
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data.cities)) setCityOptions(data.cities)
        if (!data.ok) setCityMessage(data.error || '本地城市列表读取失败')
      })
      .catch(() => setCityMessage('本地城市列表读取失败'))
    fetch('/api/cities?platform=zhilian', { cache: 'no-store' })
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data.cities)) setZhilianCityOptions(data.cities)
      })
      .catch(() => {})
    fetch('/api/cities?platform=51job', { cache: 'no-store' })
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data.cities)) setJob51CityOptions(data.cities)
      })
      .catch(() => {})
    fetch('/api/cities?platform=liepin', { cache: 'no-store' })
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data.cities)) setLiepinCityOptions(data.cities)
      })
      .catch(() => {})
  }, [])

  const selectArea = (area: ConfigArea) => {
    setActiveArea(area)
    const section = area === 'profile' ? 'profile' : area === 'sources' ? 'search' : area === 'automation' ? 'ai' : activeSafetyArea
    window.history.replaceState(null, '', `${window.location.pathname}?section=${section}`)
  }

  const selectSafetyArea = (area: SafetyArea) => {
    setActiveSafetyArea(area)
    window.history.replaceState(null, '', `${window.location.pathname}?section=${area}`)
  }

  const handleAiTest = async () => {
    if (dirty) {
      setAiTest({ testing: false, ok: false, message: '请先保存当前配置，再测试 AI 连接。' })
      return
    }
    setAiTest({ testing: true })
    try {
      const res = await fetch('/api/diagnostics/ai', { cache: 'no-store' })
      const data = await res.json()
      const check = Array.isArray(data.checks) ? data.checks[0] : null
      setAiTest({
        testing: false,
        ok: Boolean(res.ok && data.ok),
        message: check ? `${check.message}：${check.detail}` : (data.messages?.[0] || 'AI 接口未返回检测结果'),
      })
    } catch {
      setAiTest({ testing: false, ok: false, message: '无法连接本地检测接口，请确认 All In 后端正在运行。' })
    }
  }

  const handleAiServiceChange = (service: AiService) => {
    const currentService = (config?.ai?.service || (config?.ai?.provider === 'openai_compatible' ? 'custom' : 'anthropic')) as AiService
    if (service === currentService) return
    if (
      (config?.ai?.api_key || config?.ai?.api_key_masked || config?.ai?.auth_token_masked)
      && !window.confirm('切换 AI 服务商会清除当前保存的 AI 凭证，是否继续？')
    ) {
      return
    }
    const preset = AI_SERVICES[service]
    updateConfig('ai.service', service)
    updateConfig('ai.provider', preset.provider)
    updateConfig('ai.base_url', preset.baseUrl)
    updateConfig('ai.model', preset.defaultModel)
    updateConfig('ai.api_key', '')
    updateConfig('ai.api_key_masked', '')
    updateConfig('ai.auth_token_masked', '')
    updateConfig('ai.clear_credentials', true)
    setAiTest({ testing: false })
  }

  const handleCityRefresh = async () => {
    setCityRefreshing(true)
    setCityMessage('')
    try {
      const res = await fetch('/api/cities/refresh', { method: 'POST' })
      const data = await res.json()
      if (Array.isArray(data.cities)) setCityOptions(data.cities)
      if (!res.ok || !data.ok) throw new Error(data.error || '刷新失败，继续使用本地城市列表')
      setCityMessage(`已刷新 ${data.count} 个城市。`)
    } catch (error) {
      setCityMessage(error instanceof Error ? error.message : '刷新失败，继续使用本地城市列表')
    } finally {
      setCityRefreshing(false)
    }
  }

  const platformSearch = (platform: PlatformId) => {
    const legacy = platform === 'boss' && config?.search && typeof config.search === 'object' ? config.search : {}
    const specific = config?.platforms?.[platform]?.search && typeof config.platforms[platform].search === 'object'
      ? config.platforms[platform].search
      : {}
    return {
      ...legacy,
      ...specific,
      filters: { ...(legacy.filters || {}), ...(specific.filters || {}) },
      keywords: specific.keywords?.length ? specific.keywords : legacy.keywords,
      cities: specific.cities?.length ? specific.cities : legacy.cities,
      city_codes: Object.keys(specific.city_codes || {}).length ? specific.city_codes : legacy.city_codes,
      max_pages: specific.max_pages || legacy.max_pages || (platform === 'boss' ? 3 : 1),
      sort: specific.sort || legacy.sort || 'default',
      // 0 是有效值（停用断点），必须用 ?? 而不是 ||，否则会被当成空值回退到默认。
      resume_ttl_hours: specific.resume_ttl_hours ?? legacy.resume_ttl_hours ?? DEFAULT_RESUME_TTL_HOURS,
    }
  }

  const updatePlatformSearch = (platform: PlatformId, key: string, value: any) => {
    updateConfig(`platforms.${platform}.search.${key}`, value)
    if (platform === 'boss') updateConfig(`search.${key}`, value)
  }

  const updateBossFilter = (search: any, key: keyof typeof BOSS_FILTER_OPTIONS | 'industry', value: string, multiple = true) => {
    const current = Array.isArray(search.filters?.[key]) ? search.filters[key] : []
    const next = multiple
      ? (current.includes(value) ? current.filter((item: string) => item !== value) : [...current, value])
      : (value ? [value] : [])
    updatePlatformSearch('boss', `filters.${key}`, next)
  }

  const updatePlatformCities = (platform: PlatformId, cities: string[]) => {
    const platformCityOptions = platform === 'zhilian' ? zhilianCityOptions : platform === 'liepin' ? liepinCityOptions : job51CityOptions
    const cityCodes = platform !== 'boss'
      ? Object.fromEntries(cities.map(city => {
        const found = platformCityOptions.find(option => option.name.replace(/市$/, '') === city.replace(/市$/, ''))
        return [city, found?.code || '']
      }).filter(([, code]) => code))
      : Object.fromEntries(cityOptions.filter(city => cities.includes(city.name)).map(city => [city.name, city.code]))
    updatePlatformSearch(platform, 'cities', cities)
    updatePlatformSearch(platform, 'city_codes', cityCodes)
    if (platform === 'boss') updateConfig('profile.target_cities', cities)
  }

  const setPlatformEnabled = (platform: PlatformId, enabled: boolean) => {
    updateConfig(`platforms.${platform}.enabled`, enabled)
    const currentOrder: PlatformId[] = Array.isArray(config?.collection?.default_order)
      ? config.collection.default_order.filter((item: unknown): item is PlatformId => item === 'boss' || item === 'zhilian' || item === '51job' || item === 'liepin')
      : ['boss'] as PlatformId[]
    const nextOrder = enabled
      ? [...currentOrder, ...(!currentOrder.includes(platform) ? [platform] : [])]
      : currentOrder.filter(item => item !== platform)
    updateConfig('collection.default_order', nextOrder.length ? nextOrder : ['boss'])
  }

  const setCollectionOrder = (value: string) => {
    const enabled = (['boss', 'zhilian', '51job', 'liepin'] as PlatformId[]).filter(platform => config?.platforms?.[platform]?.enabled !== false)
    const requested = value.split(',').filter((item): item is PlatformId => item === 'boss' || item === 'zhilian' || item === '51job' || item === 'liepin')
    const next = [...requested, ...enabled.filter(platform => !requested.includes(platform))]
    updateConfig('collection.default_order', next.length ? next : ['boss'])
  }

  if (loading) {
    return <div className="flex items-center justify-center h-full text-muted text-sm">加载中...</div>
  }

  if (error || !config) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="max-w-md rounded-[10px] border border-card-border bg-muted-surface p-6 text-center">
          <div className="text-sm font-semibold text-foreground">配置加载失败</div>
          <p className="mt-2 text-xs leading-6 text-muted">
            请确认后端服务已启动：在项目根目录运行 allin web，或启动 127.0.0.1:8686 后刷新页面。
          </p>
          {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
          <Button className="mt-4" size="sm" onClick={resetConfig}>重试</Button>
        </div>
      </div>
    )
  }

  const bossSearchEstimate = platformSearch('boss')
  const bossEstimateKeywords = Array.isArray(bossSearchEstimate.keywords) ? bossSearchEstimate.keywords : []
  const bossEstimateCities = Array.isArray(bossSearchEstimate.cities) && bossSearchEstimate.cities.length
    ? bossSearchEstimate.cities
    : (config.profile?.target_cities || [])
  const bossEstimateMaxPages = Math.max(Number(bossSearchEstimate.max_pages) || 1, 1)
  const bossTheoreticalPages = bossEstimateKeywords.length * bossEstimateCities.length * bossEstimateMaxPages
  const bossDailySearchLimit = Math.max(Number(config.collection?.daily_search_page_limit) || 60, 1)
  const bossTheoreticalExceedsLimit = bossTheoreticalPages > bossDailySearchLimit

  const activeAreaMeta = CONFIG_AREAS.find(item => item.key === activeArea) || CONFIG_AREAS[0]

  return (
    <div className="space-y-4 pb-20 md:pb-0">
      <div className="sticky top-0 z-20 -mx-1 flex flex-wrap items-center justify-between gap-2 border-b border-card-border bg-background/95 px-1 py-2 backdrop-blur-sm">
        <div className="min-w-0">
          <div className="text-xs font-medium text-muted">{dirty ? '有未保存的更改' : '配置已同步'}</div>
          {message && <div className={`mt-0.5 text-xs ${message.type === 'success' ? 'text-success' : 'text-danger'}`}>{message.text}</div>}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={resetConfig} disabled={!dirty}><RotateCcw className="mr-1 h-3.5 w-3.5" />重置</Button>
          <Button size="sm" onClick={saveConfig} disabled={saving || !dirty}><Save className="mr-1 h-3.5 w-3.5" />{saving ? '保存中…' : '保存更改'}</Button>
        </div>
      </div>

      <nav aria-label="配置分类" className="hidden grid-cols-4 overflow-hidden rounded-[10px] border border-card-border bg-card md:grid">
        {CONFIG_AREAS.map(item => (
          <button
            key={item.key}
            type="button"
            onClick={() => selectArea(item.key)}
            className={`border-r border-card-border px-4 py-3 text-left last:border-r-0 ${activeArea === item.key ? 'bg-muted-surface text-primary' : 'text-muted hover:bg-muted-surface/60 hover:text-foreground'}`}
          >
            <span className="block text-sm font-semibold">{item.label}</span>
            <span className="mt-1 block text-[11px] leading-4">{item.description}</span>
          </button>
        ))}
      </nav>

      <label className="block md:hidden">
        <span className="mb-1.5 block text-xs font-medium text-muted">配置类别</span>
        <Select value={activeArea} onChange={event => selectArea(event.target.value as ConfigArea)}>
          {CONFIG_AREAS.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}
        </Select>
      </label>

      <section className="rounded-xl border border-card-border bg-card">
        <header className="border-b border-card-border px-4 py-4 md:px-5">
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-foreground">{activeAreaMeta.label}</h2>
          <p className="mt-1 text-xs text-muted">{activeAreaMeta.description}</p>
        </header>
        <div className="p-4 md:p-5">
        {activeArea === 'profile' && <SectionCard title="个人信息">
          <div className="space-y-4">
            <ResumeUploadSection
              currentResumePath={config.profile?.resume_path || ''}
              updateConfig={updateConfig}
            />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="最高学历">
                <Select value={config.profile?.education || ''} onChange={e => updateConfig('profile.education', e.target.value)}>
                  <option value="">未设置</option>
                  <option value="博士">博士</option>
                  <option value="硕士">硕士</option>
                  <option value="本科">本科</option>
                  <option value="大专">大专</option>
                  <option value="其他">其他</option>
                </Select>
              </Field>
              <Field label="求职招聘类型">
                <Select value={config.profile?.recruitment_type || ''} onChange={e => updateConfig('profile.recruitment_type', e.target.value)}>
                  <option value="">未设置</option>
                  <option value="campus">校招</option>
                  <option value="experienced">社招</option>
                  <option value="both">校招、社招均可</option>
                </Select>
              </Field>
            </div>
            <Field label="招呼语偏好">
              <textarea
                value={config.profile?.greeting_preference || ''}
                onChange={e => updateConfig('profile.greeting_preference', e.target.value)}
                placeholder="例如：语气简洁；不要主动询问薪资；不要提能否出差"
                rows={3}
                maxLength={500}
                className="w-full resize-y rounded-md border border-card-border bg-muted-surface px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted focus:border-primary"
              />
              <p className="mt-1 text-xs text-muted">仅补充语气和内容偏好，不能覆盖真实简历与安全规则。</p>
            </Field>
            <NumberRangeField
              label="期望薪资范围（K）"
              minValue={config.profile?.salary_min ?? 0}
              maxValue={config.profile?.salary_max ?? 0}
              onMinChange={value => updateConfig('profile.salary_min', value)}
              onMaxChange={value => updateConfig('profile.salary_max', value)}
              min={0}
              max={200}
            />
            <Field label={`薪资上限放宽倍数：${config.profile?.salary_ceil_ratio ?? 1.5}`}>
              <Slider
                value={config.profile?.salary_ceil_ratio ?? 1.5}
                onChange={value => updateConfig('profile.salary_ceil_ratio', value)}
                min={1}
                max={5}
                step={0.1}
              />
              <p className="mt-1 text-xs text-muted">按岗位薪资区间下限判断；下限超过最高薪资 × 放宽倍数时会在 AI 评分前跳过。</p>
            </Field>
            <div className="flex items-center justify-between rounded-xl border border-card-border bg-muted-surface px-3 py-2">
              <div>
                <label className="text-xs text-foreground">过滤面议/无法解析薪资</label>
                <p className="mt-1 text-xs text-muted">关闭后这类岗位会保留给 AI 综合判断。</p>
              </div>
              <Switch checked={config.profile?.filter_unparsed_salary ?? true} onChange={v => updateConfig('profile.filter_unparsed_salary', v)} />
            </div>
            <Field label="排除关键词">
              <TagsInput value={config.profile?.deal_breakers || []} onChange={v => updateConfig('profile.deal_breakers', v)} placeholder="如：外包、996" />
            </Field>
            <Field label="JD 排除关键词">
              <TagsInput value={config.profile?.jd_deal_breakers || []} onChange={v => updateConfig('profile.jd_deal_breakers', v)} placeholder="如：需频繁出差、纯销售" />
              <p className="mt-1 text-xs text-muted">完整 JD 含这些词时会在 AI 评分前跳过。</p>
            </Field>
            <Field label="屏蔽公司">
              <TagsInput value={config.profile?.blocked_companies || []} onChange={v => updateConfig('profile.blocked_companies', v)} placeholder="输入公司名称或关键词" />
              <p className="mt-1 text-xs text-muted">公司名包含这些词时不采集，也不会进入 AI 评分。</p>
            </Field>
            <div className="flex items-center justify-between">
              <label className="text-xs text-foreground">接受实习/管培岗位</label>
              <Switch checked={config.profile?.allow_internship ?? false} onChange={v => updateConfig('profile.allow_internship', v)} />
            </div>
          </div>
        </SectionCard>}

        {activeArea === 'sources' && <SectionCard title="平台与采集设置">
          <div className="space-y-4">
            <p className="text-xs leading-5 text-muted">
              BOSS 直聘与智联招聘支持自动投递；前程无忧和猎聘负责采集与评分，投递后可在岗位池手动标记。
            </p>
            <div className="hidden grid-cols-4 rounded-lg border border-card-border bg-muted-surface p-1 sm:grid" role="tablist" aria-label="招聘平台">
              {(['boss', 'zhilian', '51job', 'liepin'] as PlatformId[]).map(item => (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={activePlatform === item}
                  onClick={() => setActivePlatform(item)}
                  className={`rounded-md px-2 py-2 text-xs font-medium transition-colors ${activePlatform === item ? 'bg-card text-primary' : 'text-muted hover:text-foreground'}`}
                >
                  {PLATFORM_SHORT_LABELS[item]}
                </button>
              ))}
            </div>
            <Select className="sm:hidden" value={activePlatform} onChange={event => setActivePlatform(event.target.value as PlatformId)} aria-label="招聘平台">
              {(['boss', 'zhilian', '51job', 'liepin'] as PlatformId[]).map(item => <option key={item} value={item}>{PLATFORM_LABELS[item]}</option>)}
            </Select>
            {([activePlatform] as PlatformId[]).map(platform => {
              const search = platformSearch(platform)
              const label = PLATFORM_LABELS[platform]
              const platformCityOptions = platform === 'zhilian' ? zhilianCityOptions : platform === 'liepin' ? liepinCityOptions : job51CityOptions
              const enabled = config.platforms?.[platform]?.enabled ?? platform === 'boss'
              const cities = Array.isArray(search.cities) && search.cities.length
                ? search.cities
                : platform === 'boss' ? (config.profile?.target_cities || []) : []
              const cityInput = cities.join(', ')
              const bossFilters = search.filters && typeof search.filters === 'object' ? search.filters : {}
              return (
                <div key={platform} className={`rounded-[10px] border p-4 ${enabled ? 'border-primary/30 bg-muted-surface' : 'border-card-border bg-card opacity-70'}`}>
                  <div className="flex items-center justify-between gap-3">
                    <label className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <input type="checkbox" checked={enabled} onChange={event => setPlatformEnabled(platform, event.target.checked)} className="h-4 w-4 accent-primary" />
                      {label}
                    </label>
                    <span className="text-xs text-muted">{enabled ? '已启用' : '未启用'}</span>
                  </div>
                  {enabled && <div className="mt-4 space-y-3">
                    <Field label="搜索关键词" hint={platform === 'boss' ? '输入岗位后请按回车键确认，多岗位用","隔开，否则配置无法保存。' : undefined}>
                      <TagsInput value={Array.isArray(search.keywords) ? search.keywords : []} onChange={value => updatePlatformSearch(platform, 'keywords', value)} placeholder="如：人力、产品运营" />
                    </Field>
                    <Field label="搜索城市">
                      {platform === 'boss' ? <CityMultiSelect
                        options={cityOptions}
                        value={cities}
                        onChange={value => updatePlatformCities(platform, value)}
                        onRefresh={handleCityRefresh}
                        refreshing={cityRefreshing}
                        message={cityMessage}
                      /> : <>
                        <Input list={`config-${platform}-city-options`} value={cityInput} onChange={event => updatePlatformCities(platform, event.target.value.split(/[,，]/).map(value => value.trim()).filter(Boolean))} placeholder={platform === '51job' ? '如：上海' : '如：深圳'} />
                        <datalist id={`config-${platform}-city-options`}>{platformCityOptions.map(city => <option key={city.code} value={city.name} />)}</datalist>
                        <p className="mt-1 text-xs text-muted">{PLATFORM_SHORT_LABELS[platform]}只使用已验证的城市编码；当前内置 {platformCityOptions.length} 个城市。</p>
                        {!!cities.length && <div className="mt-2 flex flex-wrap gap-1">{cities.map((city: string) => {
                          const matched = platformCityOptions.find(option => option.name.replace(/市$/, '') === city.replace(/市$/, ''))
                          return <span key={city} className={`rounded-full px-2 py-1 text-xs ${matched ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{city} · {matched ? '已自动识别' : '暂未收录'}</span>
                        })}</div>}
                      </>}
                    </Field>
                    <div className="grid gap-3 md:grid-cols-2">
                      <Field label="最大页数">
                        <Input type="number" value={search.max_pages || (platform === 'boss' ? 3 : 1)} onChange={event => updatePlatformSearch(platform, 'max_pages', Number(event.target.value))} min={1} max={10} />
                        {platform === 'boss' && bossTheoreticalPages > 0 && (
                          <p className={`mt-1 rounded-lg px-3 py-2 text-xs ${bossTheoreticalExceedsLimit ? 'bg-amber-50 font-bold text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}>
                            理论最多 {bossTheoreticalPages} 页（{bossEstimateKeywords.length} 个关键词 × {bossEstimateCities.length} 个城市 × {bossEstimateMaxPages} 页）。
                            {bossTheoreticalExceedsLimit
                              ? ` 已超过每日 ${bossDailySearchLimit} 页上限，到达上限后会提示并停止 BOSS 当前轮。`
                              : ` 未超过每日 ${bossDailySearchLimit} 页上限。`}
                          </p>
                        )}
                      </Field>
                      <Field label="排序">
                        <Select value={search.sort || 'default'} onChange={event => updatePlatformSearch(platform, 'sort', event.target.value)}>
                          <option value="default">默认</option>
                          {platform !== '51job' && <option value="newest">最新</option>}
                        </Select>
                      </Field>
                    </div>
                    {platform !== 'boss' && <Field label="断点续采有效期（小时）" hint="0 = 每次完整重搜">
                      <Input
                        type="number"
                        value={search.resume_ttl_hours ?? DEFAULT_RESUME_TTL_HOURS}
                        onChange={event => {
                          const raw = event.target.value
                          updatePlatformSearch(platform, 'resume_ttl_hours', raw === '' ? undefined : Math.max(0, Math.min(Number(raw), MAX_RESUME_TTL_HOURS)))
                        }}
                        min={0}
                        max={MAX_RESUME_TTL_HOURS}
                      />
                      <p className="mt-1 text-xs text-muted">
                        {(search.resume_ttl_hours ?? DEFAULT_RESUME_TTL_HOURS) === 0
                          ? `${PLATFORM_SHORT_LABELS[platform]}每次采集都会完整重搜，已完成的关键词不再跳过。`
                          : `${PLATFORM_SHORT_LABELS[platform]}在此小时内已采完的（城市, 关键词）组合会整词跳过；设为 0 可关闭。`}
                      </p>
                    </Field>}
                    {platform === 'boss' && <details className="rounded-lg border border-card-border bg-card">
                      <summary className="cursor-pointer px-3 py-2.5 text-xs font-medium text-foreground">BOSS 高级筛选</summary>
                      <div className="space-y-3 border-t border-card-border p-3">
                      <div className="grid gap-3 md:grid-cols-2">
                        <Field label="职位类型">
                          <Select value={Array.isArray(bossFilters.job_type) ? bossFilters.job_type[0] || '' : ''} onChange={event => updateBossFilter(search, 'job_type', event.target.value, false)}>
                            <option value="">不限</option>
                            {BOSS_FILTER_OPTIONS.job_type.map(option => <option key={option} value={option}>{option}</option>)}
                          </Select>
                        </Field>
                        <Field label="薪资范围">
                          <Select value={Array.isArray(bossFilters.salary) ? bossFilters.salary[0] || '' : ''} onChange={event => updateBossFilter(search, 'salary', event.target.value, false)}>
                            <option value="">不限</option>
                            {BOSS_FILTER_OPTIONS.salary.map(option => <option key={option} value={option}>{option}</option>)}
                          </Select>
                        </Field>
                      </div>
                      {(['experience', 'degree', 'scale'] as const).map(key => {
                        const labels = { experience: '工作经验', degree: '学历要求', scale: '公司规模' }
                        const selected: string[] = Array.isArray(bossFilters[key]) ? bossFilters[key] : []
                        return <Field key={key} label={labels[key]}>
                          <div className="flex flex-wrap gap-1.5">
                            {BOSS_FILTER_OPTIONS[key].map(option => <button
                              key={option}
                              type="button"
                              onClick={() => updateBossFilter(search, key, option)}
                              className={`rounded-full border px-2.5 py-1 text-xs font-bold ${selected.includes(option) ? 'border-primary bg-primary/10 text-primary' : 'border-card-border bg-card text-muted hover:border-primary/40'}`}
                            >{option}</button>)}
                          </div>
                        </Field>
                      })}
                      <Field label="行业编码">
                        <TagsInput
                          value={Array.isArray(bossFilters.industry) ? bossFilters.industry : []}
                          onChange={value => updatePlatformSearch('boss', 'filters.industry', value)}
                          placeholder="输入 BOSS 行业数字编码后按回车"
                        />
                        <p className="mt-1 text-xs text-muted">只接受数字编码；无效内容会被安全忽略。</p>
                      </Field>
                      </div>
                    </details>}
                  </div>}
                </div>
              )
            })}
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="默认执行顺序">
                <Select value={Array.isArray(config.collection?.default_order) ? config.collection.default_order.join(',') : 'boss'} onChange={event => setCollectionOrder(event.target.value)}>
                  <option value="boss">BOSS 直聘</option>
                  <option value="zhilian">智联招聘</option>
                  <option value="boss,zhilian">BOSS 直聘 → 智联招聘</option>
                  <option value="zhilian,boss">智联招聘 → BOSS 直聘</option>
                  <option value="51job">前程无忧</option>
                  <option value="liepin">猎聘</option>
                  <option value="boss,zhilian,51job">BOSS → 智联 → 前程无忧</option>
                  <option value="boss,zhilian,51job,liepin">BOSS → 智联 → 前程无忧 → 猎聘</option>
                </Select>
              </Field>
              <div className="flex items-center justify-between rounded-xl border border-card-border bg-muted-surface px-3 py-2 text-xs font-bold text-muted">
                采集后自动评分
                <Switch checked={config.collection?.auto_score_default ?? false} onChange={value => updateConfig('collection.auto_score_default', value)} />
              </div>
            </div>
          </div>
        </SectionCard>}

        {activeArea === 'automation' && <div className="space-y-8">
        <SectionCard title="评分策略">
          <div className="space-y-4">
            <Field label={`通过阈值: ${config.scoring?.threshold || 60}`}>
              <Slider value={config.scoring?.threshold || 60} onChange={v => updateConfig('scoring.threshold', v)} min={0} max={100} />
            </Field>
            <Field label="每轮最大候选数">
              <Input type="number" value={config.scoring?.max_candidates || 20} onChange={e => updateConfig('scoring.max_candidates', Number(e.target.value))} min={1} max={100} />
            </Field>
          </div>
        </SectionCard>

        <SectionCard title="模型连接与内容生成">
          <div className="space-y-4">
            <Field label="提供商">
              <Select
                value={config.ai?.service || (config.ai?.provider === 'openai_compatible' ? 'custom' : 'anthropic')}
                onChange={e => handleAiServiceChange(e.target.value as AiService)}
              >
                {Object.entries(AI_SERVICES).map(([value, preset]) => (
                  <option key={value} value={value}>{preset.label}</option>
                ))}
              </Select>
              <p className="mt-1 text-xs text-muted">
                All In 会自动配置协议和服务地址；也可安全复用环境变量 {
                  AI_SERVICES[(config.ai?.service || (config.ai?.provider === 'openai_compatible' ? 'custom' : 'anthropic')) as AiService].keyEnv
                }，不会在前端显示其内容。
              </p>
            </Field>
            <Field label="模型名称">
              <div className="flex flex-wrap gap-2">
                <Input aria-label="模型名称" className="min-w-0 flex-1 basis-40" value={config.ai?.model || ''} onChange={e => {
                  updateConfig('ai.model', e.target.value)
                  setAiTest({ testing: false })
                }} placeholder="填写服务商当前支持的模型 ID" />
                <Button type="button" variant="secondary" disabled={modelList.loading} onClick={handleFetchModels}>
                  {modelList.loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />}
                  {modelList.loading ? '获取中…' : '获取模型列表'}
                </Button>
              </div>
              {modelList.models.length > 0 && (
                <Select aria-label="可用模型" className="mt-2 pr-8 appearance-auto" value={modelList.models.includes(config.ai?.model) ? config.ai.model : ''} onChange={e => {
                  updateConfig('ai.model', e.target.value)
                  setAiTest({ testing: false })
                }}>
                  <option value="" disabled>请选择模型</option>
                  {modelList.models.map(model => <option key={model} value={model}>{model}</option>)}
                </Select>
              )}
              <p role="status" className={`mt-1 text-xs ${modelList.error ? 'text-danger' : 'text-muted'}`}>
                {modelList.message || '按当前 Base URL 和 API Key 获取，无需先保存配置。'}
              </p>
            </Field>
            <form onSubmit={event => event.preventDefault()}>
              <input type="text" autoComplete="username" value={config.ai?.service || config.ai?.provider || 'all-in'} readOnly className="sr-only" tabIndex={-1} aria-hidden="true" />
              <Field label="API Key">
                <Input type="password" autoComplete="new-password" value={config.ai?.api_key || ''} onChange={e => {
                  updateConfig('ai.api_key', e.target.value)
                  setAiTest({ testing: false })
                }} placeholder={config.ai?.api_key_masked || '也可通过环境变量设置'} />
                <p className="mt-1 text-xs text-muted">填写后优先生效；留空时才读取环境变量。</p>
              </Field>
            </form>
            <Field label="Base URL">
              <Input value={config.ai?.base_url || ''} onChange={e => {
                updateConfig('ai.base_url', e.target.value)
                setAiTest({ testing: false })
              }} placeholder="留空使用默认" />
              <p className="mt-1 text-xs text-muted">填写后优先生效；留空时使用环境变量或服务商默认地址。</p>
            </Field>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Thinking 模式">
                <Select
                  value={config.ai?.thinking || 'auto'}
                  onChange={e => updateConfig('ai.thinking', e.target.value)}
                >
                  <option value="auto">自动兼容（推荐）</option>
                  <option value="disabled">强制关闭</option>
                  <option value="enabled">强制开启</option>
                  <option value="off">不发送参数</option>
                </Select>
                <p className="mt-1 text-xs text-muted">自动模式优先获取纯文本；接口不支持 thinking 参数时会安全回退。</p>
              </Field>
              <Field label="Thinking 预算 Token">
                <Input
                  type="number"
                  value={config.ai?.thinking_budget || 2048}
                  onChange={e => updateConfig('ai.thinking_budget', Number(e.target.value))}
                  min={1024}
                  max={32768}
                  disabled={(config.ai?.thinking || 'auto') !== 'enabled'}
                />
              </Field>
            </div>
            <Field label="AI 请求超时 (秒)">
              <Input
                type="number"
                value={config.ai?.timeout_seconds || 180}
                onChange={e => updateConfig('ai.timeout_seconds', Number(e.target.value))}
                min={5}
                max={600}
              />
            </Field>
            <Field label="AI 评分并发数">
              <Select
                value={String(config.ai?.scoring_concurrency || 1)}
                onChange={e => updateConfig('ai.scoring_concurrency', Number(e.target.value))}
              >
                {[1, 2, 3].map(value => <option key={value} value={value}>{value}</option>)}
              </Select>
              <p className="mt-1 text-xs text-muted">默认 1；提高并发会增加 API 限流风险。</p>
            </Field>
            <div className="flex items-center justify-between rounded-lg border border-card-border bg-muted-surface p-3">
              <div>
                <label className="text-xs font-bold text-foreground">临界评分二次复核</label>
                <p className="mt-1 text-xs text-muted">默认关闭；开启后会增加 AI 调用次数。</p>
              </div>
              <Switch checked={config.ai?.scoring_second_review ?? false} onChange={v => updateConfig('ai.scoring_second_review', v)} />
            </div>
            <div className="rounded-[10px] border border-primary/20 bg-primary/5 p-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <label className="text-sm font-semibold text-foreground">生成招呼语优化建议</label>
                  <p className="mt-1 text-xs leading-5 text-muted">保留首次生成原文，同时生成可对比的优化预览和触发原因；关闭后只生成一版。</p>
                </div>
                <Switch
                  checked={config.ai?.greeting_style_suggestions ?? true}
                  onChange={value => updateConfig('ai.greeting_style_suggestions', value)}
                />
              </div>
              <div className="mt-3 flex items-center justify-between gap-4 border-t border-primary/10 pt-3">
                <div>
                  <label className="text-sm font-semibold text-foreground">自动采用优化版</label>
                  <p className="mt-1 text-xs leading-5 text-muted">默认关闭。关闭时，发送前必须选择保留原文或采用优化版。</p>
                </div>
                <Switch
                  checked={config.ai?.greeting_auto_apply_style ?? false}
                  disabled={(config.ai?.greeting_style_suggestions ?? true) === false}
                  onChange={value => updateConfig('ai.greeting_auto_apply_style', value)}
                />
              </div>
            </div>
            <div className="rounded-[10px] border border-card-border bg-muted-surface p-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-foreground">AI 连接检测</div>
                  <p className="mt-1 text-xs text-muted">不会消耗对话 Token；检测已保存的 Key、Base URL 和服务可用性。</p>
                </div>
                <Button variant="secondary" size="sm" onClick={handleAiTest} disabled={aiTest.testing}>
                  {aiTest.testing ? '检测中...' : '测试连接'}
                </Button>
              </div>
              {aiTest.message && (
                <p className={`mt-2 rounded-lg px-3 py-2 text-xs ${
                  aiTest.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
                }`}>
                  {aiTest.message}
                </p>
              )}
            </div>
          </div>
        </SectionCard>
        </div>}

        {activeArea === 'safety' && <div className="space-y-6">
          <div className="hidden grid-cols-5 rounded-lg border border-card-border bg-muted-surface p-1 sm:grid" role="tablist" aria-label="安全与跟进设置">
            {SAFETY_AREAS.map(item => (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={activeSafetyArea === item.key}
                onClick={() => selectSafetyArea(item.key)}
                className={`rounded-md px-2 py-2 text-xs font-medium transition-colors ${activeSafetyArea === item.key ? 'bg-card text-primary' : 'text-muted hover:text-foreground'}`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <Select className="sm:hidden" value={activeSafetyArea} onChange={event => selectSafetyArea(event.target.value as SafetyArea)} aria-label="安全与跟进设置">
            {SAFETY_AREAS.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}
          </Select>

        {activeSafetyArea === 'risk_control' && <PlatformSafetySection config={config} updateConfig={updateConfig} />}

        {activeSafetyArea === 'delivery' && <SectionCard title="发送安全">
          <div className="space-y-4">
            <h4 className="text-xs font-semibold text-foreground">通用发送限制</h4>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="每日发送上限">
                <Input type="number" value={config.throttle?.daily_limit || 30} onChange={e => updateConfig('throttle.daily_limit', Number(e.target.value))} />
              </Field>
              <NumberRangeField
                label="发送间隔范围（秒）"
                minValue={config.throttle?.interval_min ?? 60}
                maxValue={config.throttle?.interval_max ?? 180}
                onMinChange={value => updateConfig('throttle.interval_min', value)}
                onMaxChange={value => updateConfig('throttle.interval_max', value)}
                min={10}
                max={600}
              />
            </div>
            <div className="grid items-end gap-4 md:grid-cols-2">
              <div className="flex h-9 items-center justify-between rounded-md border border-card-border bg-muted-surface px-3">
                <label className="text-xs text-foreground">发送前模拟浏览</label>
                <Switch checked={config.throttle?.browse_before_greet ?? true} onChange={v => updateConfig('throttle.browse_before_greet', v)} />
              </div>
              <NumberRangeField
                label="模拟浏览时长范围（秒）"
                minValue={config.throttle?.browse_duration_min ?? 15}
                maxValue={config.throttle?.browse_duration_max ?? 30}
                onMinChange={value => updateConfig('throttle.browse_duration_min', value)}
                onMaxChange={value => updateConfig('throttle.browse_duration_max', value)}
                min={5}
                max={120}
                disabled={!(config.throttle?.browse_before_greet ?? true)}
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="发送时间窗口">
                <TagsInput value={config.throttle?.send_windows || ['09:00-16:00']} onChange={v => updateConfig('throttle.send_windows', v)} placeholder="HH:MM-HH:MM" />
                <p className="mt-1 text-xs text-muted">当天最后一个窗口结束时自动停止。</p>
              </Field>
              <Field label="随机休息概率">
                <Input type="number" value={config.throttle?.day_off_probability || 0.05} onChange={e => updateConfig('throttle.day_off_probability', Number(e.target.value))} step={0.01} min={0} max={1} />
              </Field>
            </div>

            <div className="mt-6 border-t border-card-border pt-4">
              <h4 className="text-xs font-semibold text-foreground">BOSS 直聘平台专属</h4>
              <p className="mt-1 text-xs text-muted">以下设置仅作用于 BOSS 直聘的采集、投递和监测流程。</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="单日搜索页上限">
                <Input type="number" value={config.collection?.daily_search_page_limit ?? 60} onChange={e => updateConfig('collection.daily_search_page_limit', Number(e.target.value))} min={1} max={200} />
                {bossTheoreticalPages > 0 && (
                  <p className={`mt-1 text-xs ${bossTheoreticalExceedsLimit ? 'font-bold text-amber-700' : 'text-muted'}`}>
                    当前搜索组合理论最多 {bossTheoreticalPages} 页；{bossTheoreticalExceedsLimit ? `超过本上限 ${bossDailySearchLimit} 页，到达上限后会提示并停止当前轮。` : '未超过本上限。'}
                  </p>
                )}
              </Field>
              <Field label="单日详情页尝试上限">
                <Input type="number" value={config.collection?.daily_detail_page_limit ?? 150} onChange={e => updateConfig('collection.daily_detail_page_limit', Number(e.target.value))} min={1} max={500} />
              </Field>
              <Field label="连续页面失败停止阈值">
                <Input type="number" value={config.collection?.max_consecutive_page_failures ?? 3} onChange={e => updateConfig('collection.max_consecutive_page_failures', Number(e.target.value))} min={1} max={10} />
              </Field>
              <NumberRangeField
                label="风险暂停范围（分钟）"
                minValue={config.collection?.risk_pause_min_minutes ?? 5}
                maxValue={config.collection?.risk_pause_max_minutes ?? 10}
                onMinChange={value => updateConfig('collection.risk_pause_min_minutes', value)}
                onMaxChange={value => updateConfig('collection.risk_pause_max_minutes', value)}
                min={1}
                max={60}
              />
              <Field label="操作间隔倍率">
                <Input type="number" value={config.collection?.collection_delay_multiplier ?? 1.5} onChange={e => updateConfig('collection.collection_delay_multiplier', Number(e.target.value))} min={1} max={5} step={0.1} />
                <p className="mt-1 text-xs text-muted">同时作用于采集和监测的页面操作与每轮等待；数值越大，间隔越长。</p>
              </Field>
              <NumberRangeField
                label="采集后投递冷却范围（分钟）"
                minValue={config.collection?.delivery_cooldown_min_minutes ?? 5}
                maxValue={config.collection?.delivery_cooldown_max_minutes ?? 15}
                onMinChange={value => updateConfig('collection.delivery_cooldown_min_minutes', value)}
                onMaxChange={value => updateConfig('collection.delivery_cooldown_max_minutes', value)}
                min={0}
                max={240}
              />
            </div>
            <p className="text-xs text-muted">采集完成后，每次会在设定区间内随机等待后再投递；默认为 5–15 分钟，单独采集不受影响。</p>
            <Field label="单日页面访问总上限">
              <Input type="number" value={config.safety?.daily_platform_page_limit ?? 500} onChange={e => updateConfig('safety.daily_platform_page_limit', Number(e.target.value))} min={1} max={2000} />
              <p className="mt-1 text-xs text-muted">合计采集、投递和监测打开的页面；其他平台不占用。</p>
            </Field>
          </div>
        </SectionCard>}

        {activeSafetyArea === 'monitor' && <SectionCard title="HR 监测">
          <div className="space-y-4">
            <Field label="检查间隔 (分钟)">
              <Input type="number" value={config.monitor?.interval || 30} onChange={e => updateConfig('monitor.interval', Number(e.target.value))} min={1} max={120} />
              <p className="mt-1 text-xs text-muted">单独监测会立即检查一次；后续轮询还会乘以 BOSS 操作间隔倍率。</p>
            </Field>
            <Field label="全流程首次监测冷却 (分钟)">
              <Input type="number" value={config.monitor?.initial_cooldown_minutes ?? 10} onChange={e => updateConfig('monitor.initial_cooldown_minutes', Number(e.target.value))} min={0} max={120} />
              <p className="mt-1 text-xs text-muted">仅运行全流程发送结束后生效；单独监测立即检查，停止任务可取消等待。</p>
            </Field>
            <Field label="聊天页 URL">
              <Input value={config.monitor?.chat_url || ''} onChange={e => updateConfig('monitor.chat_url', e.target.value)} />
            </Field>
            <Field label="每轮最多处理对话数">
              <Input type="number" value={config.monitor?.max_conversations_per_cycle ?? 5} onChange={e => updateConfig('monitor.max_conversations_per_cycle', Number(e.target.value))} min={1} max={20} />
            </Field>
            <Field label="连续页面失败停止阈值">
              <Input type="number" value={config.monitor?.max_consecutive_page_failures ?? 3} onChange={e => updateConfig('monitor.max_consecutive_page_failures', Number(e.target.value))} min={1} max={10} />
            </Field>
            <Field label="每轮最多发简历数">
              <Input type="number" value={config.monitor?.max_resume_sends_per_cycle || 5} onChange={e => updateConfig('monitor.max_resume_sends_per_cycle', Number(e.target.value))} min={1} />
            </Field>
            <div className="flex items-center justify-between rounded-[10px] border border-card-border bg-muted-surface p-4">
              <div>
                <label className="text-sm font-semibold text-foreground">检测到 HR 问题时自动回复</label>
                <p className="mt-1 text-xs text-muted">默认关闭。关闭时只生成回复建议，需要你在“监测执行”中确认后发送。</p>
              </div>
              <Switch checked={config.monitor?.auto_reply_hr_questions ?? false} onChange={v => updateConfig('monitor.auto_reply_hr_questions', v)} />
            </div>
          </div>
        </SectionCard>}

        {activeSafetyArea === 'follow_up' && <SectionCard title="自动跟进">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <label className="text-xs text-foreground">启用自动跟进</label>
              <Switch checked={config.follow_up?.enabled ?? false} onChange={v => updateConfig('follow_up.enabled', v)} />
            </div>
            <Field label="跟进间隔 (小时)">
              <Input type="number" value={config.follow_up?.interval_hours || 48} onChange={e => updateConfig('follow_up.interval_hours', Number(e.target.value))} min={12} max={168} />
            </Field>
            <div className="flex items-center justify-between">
              <label className="text-xs text-foreground">跳过周末节假日</label>
              <Switch checked={config.follow_up?.skip_weekends ?? true} onChange={v => updateConfig('follow_up.skip_weekends', v)} />
            </div>
          </div>
        </SectionCard>}

        {activeSafetyArea === 'data' && <SectionCard title="数据记录">
          <div className="space-y-4">
            <Field label="历史记录文件路径">
              <Input value={config.dedup?.history_file || ''} onChange={e => updateConfig('dedup.history_file', e.target.value)} />
            </Field>
          </div>
        </SectionCard>}
        </div>}
        </div>
      </section>
    </div>
  )
}

// Helper components
function PlatformSafetySection({
  config,
  updateConfig,
}: {
  config: Record<string, any>
  updateConfig: (path: string, value: unknown) => void
}) {
  type PlatformStatus = {
    platform: string
    locked: boolean
    reason: string | null
    locked_until: string | null
    remaining_seconds: number
    today_pages: number
  }

  const [statuses, setStatuses] = useState<Record<string, PlatformStatus>>({})
  const [loading, setLoading] = useState(false)
  const [unlocking, setUnlocking] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const REASON_LABELS: Record<string, string> = {
    captcha: '检测到验证码',
    rate_limit: '请求频率过高',
    blocked: '账号或访问被拦截',
    login_required: '登录状态失效',
    consecutive_errors: '连续错误触发保护',
    consecutive_page_failures: '连续页面加载失败',
    daily_platform_page_limit: '超过单日页面访问上限',
    persistent_risk_lock: '安全冷却生效中',
  }

  const fetchStatus = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/safety/status')
      if (res.ok) {
        const data = await res.json()
        if (data.platforms) {
          setStatuses(data.platforms)
        }
      }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    const timer = setInterval(fetchStatus, 8000)
    return () => clearInterval(timer)
  }, [])

  const handleUnlock = async (platform: string) => {
    setUnlocking(platform)
    setMessage(null)
    try {
      const res = await fetch('/api/safety/unlock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        const pLabel = platform === 'all' ? '所有平台' : PLATFORM_LABELS[platform] || platform
        setMessage(`已成功解除 ${pLabel} 的安全冷却锁`)
        if (data.platforms) {
          setStatuses(data.platforms)
        } else {
          fetchStatus()
        }
      } else {
        setMessage(`解除失败: ${data.error || '未知错误'}`)
      }
    } catch {
      setMessage('网络错误，解除冷却失败')
    } finally {
      setUnlocking(null)
    }
  }

  const platformsList = ['boss', 'zhilian', '51job', 'liepin']
  const hasAnyLock = Object.values(statuses).some(s => s.locked)

  return (
    <SectionCard title="平台风控与冷却">
      <div className="space-y-6">
        {/* Real-time Status */}
        <div>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-xs font-semibold text-foreground">多平台实时状态与安全锁</h4>
              <p className="mt-0.5 text-[11px] text-muted">
                各平台采用独立安全锁隔离机制；若某平台遭遇风控冷却，其他平台正常工作不受阻碍。
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={fetchStatus}
                disabled={loading}
                className="h-7 text-xs"
              >
                <RefreshCw className={`mr-1 h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
                刷新状态
              </Button>
              {hasAnyLock && (
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  onClick={() => handleUnlock('all')}
                  disabled={unlocking === 'all'}
                  className="h-7 text-xs"
                >
                  {unlocking === 'all' ? (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ) : (
                    <Unlock className="mr-1 h-3 w-3" />
                  )}
                  一键解除全部冷却
                </Button>
              )}
            </div>
          </div>

          {message && (
            <div className="mb-3 rounded-lg bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800">
              {message}
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {platformsList.map(platformKey => {
              const status = statuses[platformKey] || {
                platform: platformKey,
                locked: false,
                reason: null,
                locked_until: null,
                remaining_seconds: 0,
                today_pages: 0,
              }
              const label = PLATFORM_LABELS[platformKey] || platformKey
              const isUnlockingThis = unlocking === platformKey
              const remainingMins = Math.ceil(status.remaining_seconds / 60)

              return (
                <div
                  key={platformKey}
                  className={`flex flex-col justify-between rounded-lg border p-3.5 transition-all ${
                    status.locked
                      ? 'border-red-300 bg-red-50/50 shadow-sm'
                      : 'border-card-border bg-card'
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-foreground">{label}</span>
                      {status.locked ? (
                        <span className="inline-flex items-center rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-700">
                          <Lock className="mr-0.5 h-2.5 w-2.5" />
                          冷却中
                        </span>
                      ) : (
                        <span className="inline-flex items-center rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                          <CheckCircle2 className="mr-0.5 h-2.5 w-2.5" />
                          运行正常
                        </span>
                      )}
                    </div>

                    <div className="mt-2.5 space-y-1 text-xs">
                      <div className="flex items-center justify-between text-muted">
                        <span>今日请求页面:</span>
                        <span className="font-medium text-foreground">{status.today_pages} 页</span>
                      </div>

                      {status.locked && (
                        <>
                          <div className="mt-1.5 flex items-start gap-1 text-red-700">
                            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                            <span className="text-[11px] leading-tight">
                              {REASON_LABELS[status.reason || ''] || status.reason || '触发风控'}
                            </span>
                          </div>
                          <div className="flex items-center gap-1 text-[11px] text-red-600">
                            <Clock className="h-3 w-3 shrink-0" />
                            <span>剩余约 {remainingMins} 分钟</span>
                          </div>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="mt-3 border-t border-card-border/60 pt-2">
                    {status.locked ? (
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => handleUnlock(platformKey)}
                        disabled={isUnlockingThis}
                        className="h-7 w-full text-xs font-medium text-red-700 hover:bg-red-100"
                      >
                        {isUnlockingThis ? (
                          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                        ) : (
                          <Unlock className="mr-1 h-3 w-3" />
                        )}
                        手动解除冷却
                      </Button>
                    ) : (
                      <div className="flex items-center justify-center py-1 text-[11px] text-muted">
                        无活跃限制
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Global Safety Defaults */}
        <div className="rounded-[10px] border border-card-border bg-muted-surface p-4">
          <h4 className="text-xs font-semibold text-foreground">全局安全风控基础阈值</h4>
          <p className="mt-1 text-xs text-muted">
            当单个平台未设置专属风控参数时，自动遵循此处的安全基准配置。
          </p>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <Field label="单平台单日页面访问总上限" hint="超过后自动停止访问该平台，次日重置">
              <Input
                type="number"
                value={config.safety?.daily_platform_page_limit ?? 500}
                onChange={e => updateConfig('safety.daily_platform_page_limit', Number(e.target.value))}
                min={10}
                max={2000}
              />
            </Field>

            <Field label="遇风控冷却时长（分钟）" hint="遇到验证码、限流或拦截时自动等待的时长">
              <Input
                type="number"
                value={config.safety?.risk_lock_minutes ?? 10}
                onChange={e => updateConfig('safety.risk_lock_minutes', Number(e.target.value))}
                min={1}
                max={180}
              />
            </Field>
          </div>
        </div>

        {/* Per-Platform Safety Overrides */}
        <div className="rounded-[10px] border border-card-border bg-card p-4">
          <h4 className="text-xs font-semibold text-foreground">各平台独立风控微调（可选覆盖）</h4>
          <p className="mt-1 text-xs text-muted">
            可为不同招聘平台单独设置敏感度和请求预算；留空时自动遵循全局设置。
          </p>

          <div className="mt-4 space-y-3">
            {platformsList.map(platformKey => {
              const label = PLATFORM_LABELS[platformKey] || platformKey
              const pSafety = config.platforms?.[platformKey]?.safety || {}
              const pageLimit = pSafety.daily_platform_page_limit ?? ''
              const lockMins = pSafety.risk_lock_minutes ?? ''

              return (
                <div
                  key={platformKey}
                  className="flex flex-col gap-3 rounded-lg border border-card-border/70 bg-muted-surface/50 p-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-[120px]">
                    <span className="text-xs font-medium text-foreground">{label}</span>
                    <div className="text-[11px] text-muted">
                      {pageLimit || lockMins ? '已自定义配置' : '遵循全局规则'}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-muted">单日上限:</span>
                      <Input
                        type="number"
                        placeholder={`默认 ${config.safety?.daily_platform_page_limit ?? 500}`}
                        value={pageLimit}
                        onChange={e => {
                          const val = e.target.value === '' ? undefined : Number(e.target.value)
                          updateConfig(`platforms.${platformKey}.safety.daily_platform_page_limit`, val)
                        }}
                        className="w-28 h-8 text-xs"
                      />
                    </div>

                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-muted">冷却(分):</span>
                      <Input
                        type="number"
                        placeholder={`默认 ${config.safety?.risk_lock_minutes ?? 10}`}
                        value={lockMins}
                        onChange={e => {
                          const val = e.target.value === '' ? undefined : Number(e.target.value)
                          updateConfig(`platforms.${platformKey}.safety.risk_lock_minutes`, val)
                        }}
                        className="w-24 h-8 text-xs"
                      />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </SectionCard>
  )
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-4 border-b border-card-border pb-3">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>
      {children}
    </section>
  )
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <label className="block text-xs text-foreground">{label}</label>
        {hint && <span className="text-[11px] leading-4 text-muted">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

function NumberRangeField({
  label,
  minValue,
  maxValue,
  onMinChange,
  onMaxChange,
  min,
  max,
  step,
  disabled = false,
}: {
  label: string
  minValue: number
  maxValue: number
  onMinChange: (value: number) => void
  onMaxChange: (value: number) => void
  min?: number
  max?: number
  step?: number
  disabled?: boolean
}) {
  const inputClassName = 'h-9 min-w-0 flex-1 bg-transparent px-2 text-center text-sm text-foreground outline-none disabled:cursor-not-allowed disabled:text-muted'

  return (
    <Field label={label}>
      <div className="flex h-9 items-center overflow-hidden rounded-md border border-card-border bg-card focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/30">
        <span className="shrink-0 pl-3 text-[11px] text-muted">最少</span>
        <input
          aria-label={`${label}最少`}
          className={inputClassName}
          type="number"
          value={minValue}
          onChange={event => onMinChange(Number(event.target.value))}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
        />
        <span className="flex h-full shrink-0 items-center border-x border-card-border bg-muted-surface px-3 text-xs font-bold text-muted">至</span>
        <span className="shrink-0 pl-3 text-[11px] text-muted">最多</span>
        <input
          aria-label={`${label}最多`}
          className={inputClassName}
          type="number"
          value={maxValue}
          onChange={event => onMaxChange(Number(event.target.value))}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
        />
      </div>
    </Field>
  )
}

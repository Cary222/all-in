import { NavLink } from 'react-router-dom'
import { Github, LayoutDashboard, BriefcaseBusiness, Radar, Settings, Route } from 'lucide-react'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: '工作台' },
  { to: '/jobs', icon: BriefcaseBusiness, label: '岗位池' },
  { to: '/monitor', icon: Radar, label: '监测执行' },
  { to: '/config', icon: Settings, label: '配置' },
]

const GITHUB_URL = 'https://github.com/Cary222/all-in'

interface SidebarProps {
  pendingReplies?: number
}

interface NavigationItemsProps {
  pendingReplies: number
  mobile?: boolean
}

function NavigationItems({ pendingReplies, mobile = false }: NavigationItemsProps) {
  return navItems.map(item => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) => cn(
        'group relative flex min-w-0 items-center text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        mobile
          ? 'flex-col justify-center gap-1 rounded-lg px-1 py-2 text-[11px]'
          : 'gap-3 rounded-md px-3 py-2.5',
        isActive
          ? 'bg-accent/80 text-primary'
          : 'text-muted hover:bg-muted-surface hover:text-foreground'
      )}
    >
      <span className="relative flex shrink-0 items-center justify-center">
        <item.icon className={cn('h-4 w-4', mobile && 'h-[18px] w-[18px]')} strokeWidth={1.8} aria-hidden="true" />
        {item.to === '/monitor' && pendingReplies > 0 && (
          <span
            className="absolute -right-1.5 -top-1 h-2 w-2 rounded-full bg-danger ring-2 ring-card"
            aria-label={`${pendingReplies} 个待处理事项`}
          />
        )}
      </span>
      <span className="truncate">{item.label}</span>
    </NavLink>
  ))
}

export function Sidebar({ pendingReplies: pendingRepliesProp }: SidebarProps) {
  const [pendingReplies, setPendingReplies] = useState(pendingRepliesProp ?? 0)

  useEffect(() => {
    if (pendingRepliesProp !== undefined) {
      setPendingReplies(pendingRepliesProp)
      return
    }

    const fetchPendingReplies = async () => {
      try {
        const res = await fetch('/api/history/unresolved-replies/count')
        const data = await res.json()
        setPendingReplies(Number(data.count) || 0)
      } catch {
        setPendingReplies(0)
      }
    }

    fetchPendingReplies()
    const interval = setInterval(fetchPendingReplies, 30000)
    return () => clearInterval(interval)
  }, [pendingRepliesProp])

  return (
    <>
      <aside className="hidden w-56 shrink-0 flex-col border-r border-card-border bg-card md:flex">
        <div className="flex h-16 shrink-0 items-center border-b border-card-border px-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Route className="h-[18px] w-[18px]" strokeWidth={2} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold tracking-[-0.02em] text-foreground">All In</div>
              <div className="mt-0.5 truncate font-mono text-[10px] text-muted">v2.4.0 本地版</div>
            </div>
          </div>
        </div>

        <nav aria-label="主导航" className="flex-1 space-y-1 px-3 py-4">
          <NavigationItems pendingReplies={pendingReplies} />
        </nav>

        <div className="border-t border-card-border p-3">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-3 rounded-md px-3 py-2.5 text-xs font-medium text-muted transition-colors hover:bg-muted-surface hover:text-foreground"
          >
            <Github className="h-4 w-4 shrink-0" strokeWidth={1.8} aria-hidden="true" />
            <span className="truncate">项目仓库</span>
          </a>
        </div>
      </aside>

      <nav
        aria-label="移动端主导航"
        className="fixed inset-x-3 bottom-3 z-50 grid grid-cols-4 gap-1 rounded-xl border border-card-border bg-card/95 p-1.5 shadow-[0_12px_32px_rgba(24,33,29,0.12)] backdrop-blur-md md:hidden"
      >
        <NavigationItems pendingReplies={pendingReplies} mobile />
      </nav>
    </>
  )
}

import { Link, useLocation } from 'react-router-dom'

const NAV_ITEMS = [
  { path: '/', label: '教室' },
  { path: '/relationships', label: '关系网' },
  { path: '/gossip', label: '八卦' },
  { path: '/timeline', label: '情绪线' },
]

export function Header() {
  const location = useLocation()

  return (
    <header className="sticky top-0 z-50 bg-paper/80 backdrop-blur-sm border-b border-thought-border">
      <div className="max-w-6xl mx-auto px-4 h-12 flex items-center justify-between">
        <Link to="/" className="font-hand text-xl text-ink hover:text-amber transition-colors min-h-[44px] flex items-center">
          SimCampus
        </Link>
        <nav className="flex gap-1">
          {NAV_ITEMS.map((item) => {
            const active = item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path)
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`px-4 py-2.5 min-h-[44px] flex items-center rounded-md text-sm transition-colors ${
                  active
                    ? 'bg-amber/15 text-amber font-medium'
                    : 'text-ink-light hover:text-ink hover:bg-black/5'
                }`}
              >
                {item.label}
              </Link>
            )
          })}
        </nav>
      </div>
    </header>
  )
}

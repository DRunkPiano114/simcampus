import { useWorldStore } from '../../stores/useWorldStore'
import type { ViewMode } from '../../lib/types'

export function TopBar() {
  const mode = useWorldStore(s => s.mode)
  const setMode = useWorldStore(s => s.setMode)
  const mindReading = useWorldStore(s => s.mindReadingEnabled)
  const toggleMindReading = useWorldStore(s => s.toggleMindReading)
  const currentDay = useWorldStore(s => s.currentDay)
  const meta = useWorldStore(s => s.meta)
  const setCurrentDay = useWorldStore(s => s.setCurrentDay)

  const dayNum = currentDay.replace('day_', '')
  const days = meta?.days ?? [currentDay]

  return (
    <div className="absolute top-0 left-0 right-0 z-30 flex items-center justify-between px-4 py-2 bg-gradient-to-b from-black/60 to-transparent pointer-events-none">
      {/* Left: day nav */}
      <div className="flex items-center gap-2 pointer-events-auto">
        <span className="text-white/70 text-sm font-medium">Day</span>
        <div className="flex gap-1">
          {days.map(d => {
            const n = d.replace('day_', '')
            return (
              <button
                key={d}
                onClick={() => setCurrentDay(d)}
                className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                  d === currentDay
                    ? 'bg-amber-500 text-white'
                    : 'bg-white/10 text-white/60 hover:bg-white/20 hover:text-white'
                }`}
              >
                {n}
              </button>
            )
          })}
        </div>
        <span className="text-white/40 text-xs ml-2">
          {meta?.current_date ?? ''}
        </span>
      </div>

      {/* Center: title */}
      <div className="text-white/90 text-sm font-medium tracking-wide">
        Sim班 <span className="text-white/40">—</span>{' '}
        <span className="text-amber-400/80">第{dayNum}天</span>
      </div>

      {/* Right: controls */}
      <div className="flex items-center gap-3 pointer-events-auto">
        {/* Mode toggle */}
        <div className="flex bg-white/10 rounded-full p-0.5">
          {(['explore', 'broadcast'] as ViewMode[]).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                mode === m
                  ? 'bg-white/20 text-white'
                  : 'text-white/50 hover:text-white/70'
              }`}
            >
              {m === 'explore' ? '探索' : '放映'}
            </button>
          ))}
        </div>

        {/* Mind-reading toggle */}
        <button
          onClick={toggleMindReading}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-all ${
            mindReading
              ? 'bg-rose-500/80 text-white shadow-lg shadow-rose-500/30'
              : 'bg-white/10 text-white/60 hover:bg-white/20'
          }`}
        >
          <span className="text-sm">{mindReading ? '🧠' : '👁️'}</span>
          读心
        </button>
      </div>
    </div>
  )
}

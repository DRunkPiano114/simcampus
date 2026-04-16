import { useMemo, useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { useWorldStore } from '../../stores/useWorldStore'
import { RolePlaySetup } from './RolePlaySetup'
import { LOCATION_ICONS } from '../../lib/constants'
import { groupScenesByTimeSlot } from '../../lib/sceneGroup'

export function TopBar() {
  const currentDay = useWorldStore(s => s.currentDay)
  const meta = useWorldStore(s => s.meta)
  const setCurrentDay = useWorldStore(s => s.setCurrentDay)
  const scenes = useWorldStore(s => s.scenes)
  const sceneIdx = useWorldStore(s => s.currentSceneIndex)
  const setSceneIndex = useWorldStore(s => s.setCurrentSceneIndex)

  const [showRolePlaySetup, setShowRolePlaySetup] = useState(false)
  const [sceneMenuOpen, setSceneMenuOpen] = useState(false)
  const [dayMenuOpen, setDayMenuOpen] = useState(false)
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const dayMenuRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  const days = meta?.days ?? [currentDay]
  const dayNum = currentDay.replace('day_', '')

  const slots = useMemo(() => groupScenesByTimeSlot(scenes), [scenes])
  // scenes.json entries carry a semantic `scene_index` from the backend, but
  // the export filter drops trivial scenes without renumbering — so that
  // field no longer equals array position. Navigation uses array position
  // everywhere else (store + data loader), so we map scene → array index here.
  const sceneArrayIndex = useMemo(() => new Map(scenes.map((s, i) => [s, i])), [scenes])
  const currentScene = scenes[sceneIdx]

  useEffect(() => {
    const ctl = new AbortController()
    const timer = setTimeout(() => ctl.abort(), 1500)
    fetch('/api/health', { signal: ctl.signal })
      .then(r => setApiOnline(r.ok))
      .catch(() => setApiOnline(false))
      .finally(() => clearTimeout(timer))
    return () => { ctl.abort(); clearTimeout(timer) }
  }, [])

  useEffect(() => {
    if (!sceneMenuOpen && !dayMenuOpen) return
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node
      if (sceneMenuOpen && menuRef.current && !menuRef.current.contains(target)) {
        setSceneMenuOpen(false)
      }
      if (dayMenuOpen && dayMenuRef.current && !dayMenuRef.current.contains(target)) {
        setDayMenuOpen(false)
      }
    }
    window.addEventListener('mousedown', onClick)
    return () => window.removeEventListener('mousedown', onClick)
  }, [sceneMenuOpen, dayMenuOpen])

  return (
    <div className="relative z-30 flex items-center justify-between px-4 py-2 bg-gray-900/85 backdrop-blur flex-shrink-0 border-b border-white/10 pointer-events-none">
      {/* Left: day + scene dropdown */}
      <div className="flex items-center gap-3 pointer-events-auto">
        <div ref={dayMenuRef} className="relative">
          <button
            onClick={() => setDayMenuOpen(o => !o)}
            className="flex items-center gap-1.5 px-3 py-1 rounded bg-white/10 hover:bg-white/20 text-xs text-white/80"
          >
            <span className="text-white/60">Day</span>
            <span className="font-mono font-medium">{dayNum}</span>
            <span className="text-white/40">▾</span>
          </button>
          {dayMenuOpen && (
            <div className="absolute top-full left-0 mt-1 bg-gray-900/95 backdrop-blur border border-white/10 rounded-lg shadow-xl max-h-[60vh] overflow-y-auto min-w-[120px] py-1">
              {days.map(d => {
                const n = d.replace('day_', '')
                const isActive = d === currentDay
                return (
                  <button
                    key={d}
                    onClick={() => { setCurrentDay(d); setDayMenuOpen(false) }}
                    className={`w-full text-left flex items-center gap-2 px-3 py-1.5 text-xs font-mono ${
                      isActive ? 'bg-white/15 text-white' : 'text-white/60 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    <span className="text-white/40">Day</span>
                    <span>{n}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        <div ref={menuRef} className="relative">
          <button
            onClick={() => setSceneMenuOpen(o => !o)}
            className="flex items-center gap-1.5 px-3 py-1 rounded bg-white/10 hover:bg-white/20 text-xs text-white/80"
          >
            {currentScene && (
              <>
                <span className="text-white/40">{currentScene.time}</span>
                <span>{LOCATION_ICONS[currentScene.location] ?? '📍'}</span>
                <span>{currentScene.name}@{currentScene.location}</span>
              </>
            )}
            <span className="text-white/40">▾</span>
          </button>
          {sceneMenuOpen && (
            <div className="absolute top-full left-0 mt-1 bg-gray-900/95 backdrop-blur border border-white/10 rounded-lg shadow-xl max-h-[60vh] overflow-y-auto min-w-[280px] py-1">
              {slots.map(slot => {
                const slotActive = slot.scenes.some(s => sceneArrayIndex.get(s) === sceneIdx)
                if (slot.scenes.length === 1) {
                  const scene = slot.scenes[0]
                  const arrIdx = sceneArrayIndex.get(scene)!
                  const isActive = arrIdx === sceneIdx
                  return (
                    <button
                      key={slot.key}
                      onClick={() => { setSceneIndex(arrIdx); setSceneMenuOpen(false) }}
                      className={`w-full text-left flex items-center gap-2 px-3 py-1.5 text-xs ${
                        isActive ? 'bg-white/15 text-white' : 'text-white/60 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      <span className="text-white/40 w-10 shrink-0">{scene.time}</span>
                      <span>{LOCATION_ICONS[scene.location] ?? '📍'}</span>
                      <span>{scene.name}</span>
                      <span className="text-white/40 ml-auto">{scene.location}</span>
                    </button>
                  )
                }
                return (
                  <div key={slot.key}>
                    <div className={`px-3 py-1 text-[10px] uppercase tracking-wider ${slotActive ? 'text-amber-400/80' : 'text-white/30'}`}>
                      {slot.time} · {slot.name}
                    </div>
                    {slot.scenes.map(scene => {
                      const arrIdx = sceneArrayIndex.get(scene)!
                      const isActive = arrIdx === sceneIdx
                      return (
                        <button
                          key={arrIdx}
                          onClick={() => { setSceneIndex(arrIdx); setSceneMenuOpen(false) }}
                          className={`w-full text-left flex items-center gap-2 pl-8 pr-3 py-1.5 text-xs ${
                            isActive ? 'bg-white/15 text-white' : 'text-white/60 hover:bg-white/10 hover:text-white'
                          }`}
                        >
                          <span>{LOCATION_ICONS[scene.location] ?? '📍'}</span>
                          <span>{scene.location}</span>
                        </button>
                      )
                    })}
                  </div>
                )
              })}
            </div>
          )}
        </div>

      </div>

      {/* Center: title */}
      <div className="text-white/90 text-sm font-medium tracking-wide pointer-events-none">
        SimCampus <span className="text-white/40">—</span>{' '}
        <span className="text-amber-400/80">第{dayNum}天</span>
      </div>

      {/* Right: 日报 (gold archive seal) + 入戏 (vermillion role-play seal) */}
      <div className="flex items-center gap-3 pointer-events-auto">
        <button
          onClick={() => navigate(`/day/${currentDay}`)}
          aria-label="日报 — 查看今天的班级日报"
          title="日报 — 查看今天的班级日报"
          className="seal-btn seal-btn--gold"
        >
          <span className="seal-btn-text">日报</span>
        </button>
        <button
          onClick={() => apiOnline && setShowRolePlaySetup(true)}
          disabled={apiOnline !== true}
          aria-label="入戏 — 扮演一名角色与同班同学对话"
          title={
            apiOnline === null
              ? '正在检查 API…'
              : apiOnline
                ? '入戏 — 扮演一名角色与同班同学对话'
                : '启动 API 服务后可用（uv run api）'
          }
          className={`seal-btn${apiOnline !== true ? ' seal-btn-disabled' : ''}`}
        >
          <span className="seal-btn-text">入戏</span>
        </button>
      </div>

      <AnimatePresence>
        {showRolePlaySetup && (
          <RolePlaySetup onClose={() => setShowRolePlaySetup(false)} />
        )}
      </AnimatePresence>
    </div>
  )
}

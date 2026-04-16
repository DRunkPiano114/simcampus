import { useWorldStore } from '../../stores/useWorldStore'
import { scoreTick } from '../../lib/drama'
import type { SceneGroup } from '../../lib/types'

/**
 * Manual tick/scene navigation. ←/→ buttons (and keyboard, wired in
 * PixiCanvas) call store.goPrev/goNext, which cross group and scene
 * boundaries automatically. The drama-intensity bars allow direct jump
 * within the current group.
 */

export function TickNav() {
  const scene = useWorldStore(s => s.currentSceneFile)
  const scenes = useWorldStore(s => s.scenes)
  const sceneIdx = useWorldStore(s => s.currentSceneIndex)
  const groupIdx = useWorldStore(s => s.activeGroupIndex)
  const tick = useWorldStore(s => s.currentTick)
  const currentDay = useWorldStore(s => s.currentDay)
  const meta = useWorldStore(s => s.meta)
  const setTick = useWorldStore(s => s.setCurrentTick)
  const setScene = useWorldStore(s => s.setCurrentSceneIndex)
  const goNext = useWorldStore(s => s.goNext)
  const goPrev = useWorldStore(s => s.goPrev)

  if (!scene) return null
  const group = scene.groups[groupIdx]
  const ticks = group && !group.is_solo ? (group as SceneGroup).ticks : []
  const tickScores = ticks.map(scoreTick)
  const maxScore = Math.max(1, ...tickScores)

  const days = meta?.days ?? []
  const dayIdx = days.indexOf(currentDay)
  const hasPrevDay = dayIdx > 0
  const hasNextDay = dayIdx >= 0 && dayIdx < days.length - 1
  const atVeryStart = sceneIdx === 0 && groupIdx === 0 && tick === 0 && !hasPrevDay
  const atVeryEnd =
    sceneIdx === scenes.length - 1 &&
    groupIdx === scene.groups.length - 1 &&
    (ticks.length === 0 || tick === ticks.length - 1) &&
    !hasNextDay

  return (
    <div className="px-4 py-2.5 border-t border-white/5 flex items-center gap-3">
      <button
        onClick={goPrev}
        disabled={atVeryStart}
        title="上一句（←）"
        className="text-white/70 hover:text-white text-base px-2 py-0.5 rounded hover:bg-white/10 disabled:opacity-25 disabled:cursor-not-allowed"
      >
        ←
      </button>

      {ticks.length > 0 ? (
        <div className="flex-1 flex items-end gap-px h-6">
          {ticks.map((_, i) => {
            const intensity = tickScores[i] / maxScore
            const isCurrent = i === tick
            return (
              <button
                key={i}
                onClick={() => setTick(i)}
                className="flex-1 relative"
                style={{ minWidth: 4 }}
                title={`tick ${i + 1}`}
              >
                <div
                  className="w-full rounded-sm transition-colors"
                  style={{
                    height: `${Math.max(4, intensity * 20)}px`,
                    background: isCurrent
                      ? '#f59e0b'
                      : `rgba(232, 230, 240, ${0.15 + intensity * 0.35})`,
                  }}
                />
                {isCurrent && (
                  <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-amber-400 rounded-full" />
                )}
              </button>
            )
          })}
        </div>
      ) : (
        <div className="flex-1 text-white/30 text-xs italic">（无 tick）</div>
      )}

      <button
        onClick={goNext}
        disabled={atVeryEnd}
        title="下一句（→）"
        className="text-white/70 hover:text-white text-base px-2 py-0.5 rounded hover:bg-white/10 disabled:opacity-25 disabled:cursor-not-allowed"
      >
        →
      </button>

      {ticks.length > 0 && (
        <span className="text-white/40 text-xs font-mono min-w-[3.5rem] text-right">
          {tick + 1}/{ticks.length}
        </span>
      )}

      <div className="flex items-center gap-1 ml-1">
        <button
          onClick={() => sceneIdx > 0 && setScene(sceneIdx - 1, true)}
          disabled={sceneIdx === 0}
          className="text-white/40 hover:text-white/70 text-xs px-1 disabled:opacity-30"
          title="上一场景（最后一拍）"
        >
          ◀场
        </button>
        <span className="text-white/30 text-[10px] font-mono min-w-[2.5rem] text-center">
          {sceneIdx + 1}/{scenes.length}
        </span>
        <button
          onClick={() => sceneIdx < scenes.length - 1 && setScene(sceneIdx + 1)}
          disabled={sceneIdx >= scenes.length - 1}
          className="text-white/40 hover:text-white/70 text-xs px-1 disabled:opacity-30"
          title="下一场景"
        >
          场▶
        </button>
      </div>
    </div>
  )
}

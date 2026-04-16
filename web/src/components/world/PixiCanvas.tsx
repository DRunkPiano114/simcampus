import { Application, extend, useApplication, useTick } from '@pixi/react'
import { Container, Graphics } from 'pixi.js'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useWorldStore } from '../../stores/useWorldStore'
import { loadMeta, loadScenes, loadSceneFile, prefetchDay, loadAgentColors, loadTilesetManifest, loadAnimatedManifest } from '../../lib/data'
import { ROOMS, TILE, derivePositions } from '../../lib/roomConfig'
import { createCharacterSprite, updateSpriteState, primeAgentColors, preloadMapSprites } from './CharacterSprite'
import { preloadTilesets } from './tilesets'
import { preloadAnimated } from './animated'
import { Camera } from './Camera'
import { BubbleOverlay, type BubbleData } from './BubbleOverlay'
import { EMOTION_EMOJIS } from '../../lib/constants'
import { Room } from './Room'
import { TopBar } from '../ui/TopBar'
import { SidePanel } from '../ui/SidePanel'
import { ErrorBoundary } from '../ui/ErrorBoundary'
import { GodModeChat } from '../ui/GodModeChat'
import { RolePlayChat } from '../ui/RolePlayChat'
// import { NarrativePanel } from '../narrative/NarrativePanel'
// import { ScriptScene } from '../narrative/ScriptScene'
import { GroupGrid } from '../narrative/GroupGrid'
import type { SceneGroup } from '../../lib/types'

extend({ Container, Graphics })

// TopBar is a flex sibling (not overlay). Side panel lives to the right.
const UI_INSET = { top: 8, bottom: 8, left: 8, right: 8 }

// --- data loading ---

function useDataLoader() {
  const { dayId: urlDayId, sceneFile: urlSceneFile } = useParams<{ dayId: string; sceneFile: string }>()
  const navigate = useNavigate()
  const location = useLocation()

  const setMeta = useWorldStore(s => s.setMeta)
  const setScenes = useWorldStore(s => s.setScenes)
  const setSceneFile = useWorldStore(s => s.setCurrentSceneFile)
  const setSceneIdx = useWorldStore(s => s.setCurrentSceneIndex)
  const setCurrentDay = useWorldStore(s => s.setCurrentDay)
  const consumePendingDayLanding = useWorldStore(s => s.consumePendingDayLanding)
  const currentDay = useWorldStore(s => s.currentDay)
  const sceneIdx = useWorldStore(s => s.currentSceneIndex)
  const scenes = useWorldStore(s => s.scenes)

  // One generation token shared across both async layers so that rapid
  // Day1→Day2→Day1 clicks can't drop a stale scene list or scene file into
  // the store.
  const genRef = useRef(0)

  useEffect(() => {
    loadMeta().then(async meta => {
      setMeta(meta)
      const [colors, tilesets, animated] = await Promise.all([
        loadAgentColors().catch(() => null),
        loadTilesetManifest().catch(() => null),
        loadAnimatedManifest().catch(() => null),
      ])
      if (colors) primeAgentColors(colors)
      await Promise.all([
        preloadMapSprites(Object.keys(meta.agents ?? {})),
        tilesets ? preloadTilesets(tilesets) : Promise.resolve(),
        animated ? preloadAnimated(animated) : Promise.resolve(),
      ])
    })
  }, [setMeta])

  // URL → store: keep `currentDay` in lockstep with `:dayId`. The URL is the
  // single source of truth on this route — without this, deep links from the
  // daily report (and the back/forward buttons) would silently fall back to
  // the store's initial day_001.
  useEffect(() => {
    if (urlDayId && urlDayId !== currentDay) {
      setCurrentDay(urlDayId)
    }
  }, [urlDayId, currentDay, setCurrentDay])

  useEffect(() => {
    // Wait for the URL→store day sync before fetching scenes, so we don't
    // briefly load and render the wrong day's scene list.
    if (urlDayId && urlDayId !== currentDay) return
    const myGen = ++genRef.current
    loadScenes(currentDay).then(s => {
      if (myGen !== genRef.current) return
      setScenes(s)
      if (s.length === 0) return
      // Explicit scene file in the URL takes priority over both the rewind
      // landing and the default-to-zero. Stale/invalid file → fall through.
      if (urlSceneFile && urlSceneFile !== 'first') {
        const idx = s.findIndex(e => e.file === urlSceneFile)
        if (idx >= 0) {
          setSceneIdx(idx)
          return
        }
      }
      const landing = consumePendingDayLanding()
      if (landing === 'end') setSceneIdx(s.length - 1, true)
      else setSceneIdx(0)
    })
    prefetchDay(currentDay).catch(() => {})
  }, [currentDay, urlDayId, urlSceneFile, setScenes, setSceneIdx, consumePendingDayLanding])

  useEffect(() => {
    const entry = scenes[sceneIdx]
    if (!entry) return
    const myGen = ++genRef.current
    loadSceneFile(currentDay, entry.file).then(file => {
      if (myGen !== genRef.current) return
      setSceneFile(file)
    })
  }, [currentDay, sceneIdx, scenes, setSceneFile])

  // store → URL: when keyboard / TopBar / TickNav advances the store past the
  // URL, replace the URL so refreshing or sharing reflects what's on screen.
  useEffect(() => {
    const entry = scenes[sceneIdx]
    if (!entry) return
    const expected = `/day/${currentDay}/scene/${entry.file}`
    if (location.pathname !== expected) {
      navigate(expected, { replace: true })
    }
  }, [currentDay, sceneIdx, scenes, location.pathname, navigate])
}

// --- world scene ---

function WorldScene() {
  const { app } = useApplication()
  const currentRoom = useWorldStore(s => s.currentRoom)
  const sceneFile = useWorldStore(s => s.currentSceneFile)
  const groupIdx = useWorldStore(s => s.activeGroupIndex)
  const currentTick = useWorldStore(s => s.currentTick)
  const focusedAgent = useWorldStore(s => s.focusedAgent)
  const meta = useWorldStore(s => s.meta)

  const worldRef = useRef<Container | null>(null)
  const cameraRef = useRef<Camera | null>(null)
  const spritesRef = useRef(new Map<string, Container>())
  const bubbleRef = useRef<BubbleOverlay | null>(null)

  useEffect(() => {
    const canvas = app.canvas as HTMLCanvasElement
    const parent = canvas.parentElement
    if (!parent) return

    let wrapper = parent.querySelector('.pixi-wrapper') as HTMLDivElement | null
    if (!wrapper) {
      wrapper = document.createElement('div')
      wrapper.className = 'pixi-wrapper'
      Object.assign(wrapper.style, {
        position: 'relative',
        width: '100%',
        height: '100%',
      })
      parent.insertBefore(wrapper, canvas)
      wrapper.appendChild(canvas)
    }

    bubbleRef.current = new BubbleOverlay(wrapper, (agentId) => {
      useWorldStore.getState().setFocusedAgent(agentId)
    })

    return () => {
      bubbleRef.current?.destroy()
    }
  }, [app])

  const worldContainerRef = useCallback((node: Container | null) => {
    worldRef.current = node
    if (node && app.canvas) {
      const cam = new Camera(node, app.canvas.width, app.canvas.height)
      const room = ROOMS[useWorldStore.getState().currentRoom]
      cam.fitToRoom(room.cols * TILE, room.rows * TILE, UI_INSET)
      cameraRef.current = cam
    }
  }, [app])

  useLayoutEffect(() => {
    const world = worldRef.current
    if (!world || !sceneFile) return

    // Destroy old sprites synchronously before paint so stale characters
    // from a previous room/scene never flash on the new room floor.
    for (const s of spritesRef.current.values()) s.destroy({ children: true })
    spritesRef.current.clear()

    const group = sceneFile.groups[groupIdx]
    if (!group) return

    const positions = derivePositions(
      currentRoom,
      group.participants,
      groupIdx,
      meta?.agents as Record<string, { seat_number: number | null }>,
    )

    for (const agentId of group.participants) {
      const name = sceneFile.participant_names[agentId] ?? agentId
      const sprite = createCharacterSprite(agentId, name)
      const pos = positions[agentId]
      if (pos) {
        sprite.x = pos.x
        sprite.y = pos.y
      }
      sprite.eventMode = 'static'
      sprite.cursor = 'pointer'
      sprite.on('pointertap', () => {
        useWorldStore.getState().setFocusedAgent(agentId)
      })
      world.addChild(sprite)
      spritesRef.current.set(agentId, sprite)
    }

    for (let gi = 0; gi < sceneFile.groups.length; gi++) {
      if (gi === groupIdx) continue
      const otherGroup = sceneFile.groups[gi]
      const otherPos = derivePositions(
        currentRoom,
        otherGroup.participants,
        gi,
        meta?.agents as Record<string, { seat_number: number | null }>,
      )
      for (const agentId of otherGroup.participants) {
        if (spritesRef.current.has(agentId)) continue
        const name = sceneFile.participant_names[agentId] ?? agentId
        const sprite = createCharacterSprite(agentId, name)
        const pos = otherPos[agentId]
        if (pos) { sprite.x = pos.x; sprite.y = pos.y }
        sprite.alpha = 0.35
        sprite.eventMode = 'static'
        sprite.cursor = 'pointer'
        sprite.on('pointertap', () => {
          useWorldStore.getState().setFocusedAgent(agentId)
        })
        world.addChild(sprite)
        spritesRef.current.set(agentId, sprite)
      }
    }
  }, [sceneFile, groupIdx, currentRoom, meta])

  useEffect(() => {
    if (!sceneFile) return
    const group = sceneFile.groups[groupIdx]

    if (!group) {
      bubbleRef.current?.setBubbles([])
      return
    }

    // Solo: single pixel balloon over the solo agent; narrative panel owns text.
    if (group.is_solo) {
      const soloId = group.participants[0]
      const emotion = group.solo_reflection.emotion
      const emoji = EMOTION_EMOJIS[emotion] ?? '😐'
      bubbleRef.current?.setBubbles([{
        agentId: soloId,
        displayName: '',
        text: emoji,
        type: 'emoji',
        emotion,
      }])
      return
    }

    const tick = (group as SceneGroup).ticks[currentTick]
    if (!tick) { bubbleRef.current?.setBubbles([]); return }

    for (const [agentId, sprite] of spritesRef.current) {
      const mind = tick.minds[agentId]
      const isActiveGroup = group.participants.includes(agentId)
      const isFocused = focusedAgent === null || focusedAgent === agentId
      const state = mind?.action_type === 'speak' ? 'talking' : 'idle'
      updateSpriteState(sprite, state as 'idle' | 'talking', !isActiveGroup || !isFocused)
    }

    // Only the speaker gets a bubble. All other emotional signal lives in
    // ObserverRow below; the stage is just "space + who's talking".
    const bubbles: BubbleData[] = []
    if (tick.public.speech) {
      const s = tick.public.speech
      bubbles.push({
        agentId: s.agent,
        displayName: sceneFile.participant_names[s.agent] ?? '',
        text: s.content,
        type: 'speech',
        target: s.target ?? undefined,
      })
    }
    bubbleRef.current?.setBubbles(bubbles)
  }, [sceneFile, groupIdx, currentTick, focusedAgent])

  useEffect(() => {
    const room = ROOMS[currentRoom]
    const cam = cameraRef.current
    if (!room || !cam) return
    cam.fitToRoom(room.cols * TILE, room.rows * TILE, UI_INSET)
  }, [currentRoom])

  // Zoom + pan camera to frame the active group's seats. Uses the same
  // derivePositions logic as sprite placement so the bbox is exact.
  useEffect(() => {
    const cam = cameraRef.current
    if (!cam || !sceneFile) return
    const group = sceneFile.groups[groupIdx]
    if (!group) return

    const positions = derivePositions(
      currentRoom,
      group.participants,
      groupIdx,
      meta?.agents as Record<string, { seat_number: number | null }>,
    )
    const coords = Object.values(positions)
    if (coords.length === 0) return

    const xs = coords.map(p => p.x)
    const ys = coords.map(p => p.y)
    const minX = Math.min(...xs)
    const maxX = Math.max(...xs)
    const minY = Math.min(...ys)
    const maxY = Math.max(...ys)

    // Pad bbox so sprites aren't flush against the viewport edge, and
    // enforce a minimum size so a single sprite doesn't zoom in absurdly far.
    const PAD = TILE * 3
    const MIN_BBOX = TILE * 6
    const bboxW = Math.max(maxX - minX, MIN_BBOX) + PAD * 2
    const bboxH = Math.max(maxY - minY, MIN_BBOX) + PAD * 2
    const cx = (minX + maxX) / 2
    const cy = (minY + maxY) / 2

    cam.panToBox(cx, cy, bboxW, bboxH, UI_INSET)
  }, [sceneFile, groupIdx, currentRoom, meta])

  useEffect(() => {
    const cam = cameraRef.current
    const canvas = app.canvas as HTMLCanvasElement
    if (!cam || !canvas) return

    const onResize = () => {
      const parent = canvas.parentElement
      if (!parent) return
      const { clientWidth: vw, clientHeight: vh } = parent
      app.renderer.resize(vw, vh)
      cam.resize(vw, vh)
      const room = ROOMS[currentRoom]
      cam.fitToRoom(room.cols * TILE, room.rows * TILE, UI_INSET)
    }

    const ro = new ResizeObserver(onResize)
    ro.observe(canvas.parentElement!)
    return () => ro.disconnect()
  }, [app, currentRoom])

  useTick(() => {
    cameraRef.current?.update()
    if (worldRef.current) {
      bubbleRef.current?.updatePositions(spritesRef.current, worldRef.current)
    }
  })

  useEffect(() => {
    const canvas = app.canvas as HTMLCanvasElement
    const cam = cameraRef.current
    if (!cam) return

    const onDown = (e: PointerEvent) => cam.onPointerDown(e.clientX, e.clientY)
    const onMove = (e: PointerEvent) => cam.onPointerMove(e.clientX, e.clientY)
    const onUp = () => cam.onPointerUp()
    const onWheel = (e: WheelEvent) => { e.preventDefault(); cam.onWheel(e.deltaY) }

    canvas.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    canvas.addEventListener('wheel', onWheel, { passive: false })

    return () => {
      canvas.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('wheel', onWheel)
    }
  }, [app])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Skip when typing into inputs (RolePlay chat etc.)
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      const store = useWorldStore.getState()
      if (e.key === 'ArrowRight' || e.key === ' ') {
        e.preventDefault()
        store.goNext()
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        store.goPrev()
      } else if (e.key === ']') {
        e.preventDefault()
        const file = store.currentSceneFile
        if (file && store.activeGroupIndex < file.groups.length - 1) {
          store.setActiveGroupIndex(store.activeGroupIndex + 1)
        }
      } else if (e.key === '[') {
        e.preventDefault()
        if (store.activeGroupIndex > 0) {
          store.setActiveGroupIndex(store.activeGroupIndex - 1)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <pixiContainer ref={worldContainerRef}>
      <Room room={currentRoom} />
    </pixiContainer>
  )
}

// --- main export ---

export function PixiCanvas() {
  useDataLoader()
  const [stageEl, setStageEl] = useState<HTMLDivElement | null>(null)


  return (
    <div className="w-screen h-screen bg-[#0d0d1a] overflow-hidden relative flex flex-col">
      <TopBar />
      <div className="flex-1 min-h-0 flex flex-row">
        <div ref={setStageEl} className="flex-1 min-h-0 relative bg-[#1a1a2e]">
          {stageEl && (
            <Application
              resizeTo={stageEl}
              background={0x1a1a2e}
              antialias={false}
              resolution={1}
            >
              <WorldScene />
            </Application>
          )}
        </div>
        <div className="w-[40%] min-w-[420px] flex-shrink-0 border-l border-white/5 min-h-0">
          <GroupGrid />
        </div>
      </div>

      <ErrorBoundary><SidePanel /></ErrorBoundary>
      <GodModeChat />
      <RolePlayChat />
    </div>
  )
}

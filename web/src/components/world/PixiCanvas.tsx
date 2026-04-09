import { Application, extend, useApplication, useTick } from '@pixi/react'
import { Container, Graphics } from 'pixi.js'
import { useCallback, useEffect, useRef } from 'react'
import { useWorldStore } from '../../stores/useWorldStore'
import { loadMeta, loadScenes, loadSceneFile, prefetchDay } from '../../lib/data'
import { ROOMS, TILE, derivePositions } from '../../lib/roomConfig'
import { createCharacterSprite, updateSpriteState } from './CharacterSprite'
import { Camera } from './Camera'
import { BubbleOverlay, type BubbleData } from './BubbleOverlay'
import { DanmuLayer } from './DanmuLayer'
import { pickDanmu } from '../../lib/drama'
import { EMOTION_EMOJIS } from '../../lib/constants'
import { Room } from './Room'
import { TopBar } from '../ui/TopBar'
import { BottomBar } from '../ui/BottomBar'
import { RoomNav } from '../ui/RoomNav'
import { SidePanel } from '../ui/SidePanel'
import { ErrorBoundary } from '../ui/ErrorBoundary'
import { GodModeChat } from '../ui/GodModeChat'
import { RolePlayChat } from '../ui/RolePlayChat'
import { playbackController } from '../../lib/PlaybackController'
import type { SceneGroup } from '../../lib/types'

extend({ Container, Graphics })

// TopBar ~48px, BottomBar ~72px, RoomNav ~180px
const UI_INSET = { top: 48, bottom: 72, left: 180, right: 0 }

// --- data loading ---

function useDataLoader() {
  const setMeta = useWorldStore(s => s.setMeta)
  const setScenes = useWorldStore(s => s.setScenes)
  const setSceneFile = useWorldStore(s => s.setCurrentSceneFile)
  const setSceneIdx = useWorldStore(s => s.setCurrentSceneIndex)
  const currentDay = useWorldStore(s => s.currentDay)
  const sceneIdx = useWorldStore(s => s.currentSceneIndex)
  const scenes = useWorldStore(s => s.scenes)

  // Load meta once
  useEffect(() => {
    loadMeta().then(m => {
      setMeta(m)
    })
  }, [setMeta])

  // Load scenes when day changes
  useEffect(() => {
    loadScenes(currentDay).then(s => {
      setScenes(s)
      if (s.length > 0) setSceneIdx(0)
    })
    prefetchDay(currentDay).catch(() => {})
  }, [currentDay, setScenes, setSceneIdx])

  // Load scene file when scene index changes
  useEffect(() => {
    const entry = scenes[sceneIdx]
    if (!entry) return
    loadSceneFile(currentDay, entry.file).then(setSceneFile)
  }, [currentDay, sceneIdx, scenes, setSceneFile])
}

// --- world scene ---

function WorldScene() {
  const { app } = useApplication()
  const currentRoom = useWorldStore(s => s.currentRoom)
  const sceneFile = useWorldStore(s => s.currentSceneFile)
  const groupIdx = useWorldStore(s => s.activeGroupIndex)
  const currentTick = useWorldStore(s => s.currentTick)
  const mindReading = useWorldStore(s => s.mindReadingEnabled)
  const focusedAgent = useWorldStore(s => s.focusedAgent)
  const mode = useWorldStore(s => s.mode)
  const meta = useWorldStore(s => s.meta)

  const worldRef = useRef<Container | null>(null)
  const cameraRef = useRef<Camera | null>(null)
  const spritesRef = useRef(new Map<string, Container>())
  const bubbleRef = useRef<BubbleOverlay | null>(null)
  const danmuRef = useRef<DanmuLayer | null>(null)
  const prevTickRef = useRef(-1)

  // Init camera, bubble overlay, danmu layer
  useEffect(() => {
    const canvas = app.canvas as HTMLCanvasElement
    const parent = canvas.parentElement
    if (!parent) return

    // Wrap canvas in relative container for overlays
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
    danmuRef.current = new DanmuLayer(wrapper)

    return () => {
      bubbleRef.current?.destroy()
      danmuRef.current?.destroy()
    }
  }, [app])

  // Setup world container with camera (only depends on app, not room)
  const worldContainerRef = useCallback((node: Container | null) => {
    worldRef.current = node
    if (node && app.canvas) {
      const cam = new Camera(node, app.canvas.width, app.canvas.height)
      const room = ROOMS[useWorldStore.getState().currentRoom]
      cam.fitToRoom(room.cols * TILE, room.rows * TILE, UI_INSET)
      cameraRef.current = cam
    }
  }, [app])

  // Manage character sprites
  useEffect(() => {
    const world = worldRef.current
    if (!world || !sceneFile) return

    // Clear old sprites
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

    // Also add other groups' characters (dimmed)
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

  // Update sprites + bubbles per tick
  useEffect(() => {
    if (!sceneFile) return
    const group = sceneFile.groups[groupIdx]
    if (!group || group.is_solo) {
      bubbleRef.current?.setBubbles([])
      // Solo: show thought bubble
      if (group?.is_solo) {
        const solo = group
        const name = sceneFile.participant_names[solo.participants[0]] ?? ''
        bubbleRef.current?.setBubbles([{
          agentId: solo.participants[0],
          displayName: name,
          text: solo.solo_reflection.inner_thought,
          type: 'thought',
        }])
      }
      return
    }

    const tick = (group as SceneGroup).ticks[currentTick]
    if (!tick) return

    // Update sprite states
    for (const [agentId, sprite] of spritesRef.current) {
      const mind = tick.minds[agentId]
      const isActiveGroup = group.participants.includes(agentId)
      const isFocused = focusedAgent === null || focusedAgent === agentId
      const state = mind?.action_type === 'speak' ? 'talking'
        : mind?.action_type === 'whisper' ? 'whispering'
        : 'idle'
      updateSpriteState(sprite, state as 'idle' | 'talking' | 'whispering', !isActiveGroup || !isFocused)
    }

    // Build bubbles
    const bubbles: BubbleData[] = []

    // Speech bubble (+ inline inner thought in mind-reading mode)
    if (tick.public.speech) {
      const s = tick.public.speech
      const mind = tick.minds[s.agent]
      bubbles.push({
        agentId: s.agent,
        displayName: sceneFile.participant_names[s.agent] ?? '',
        text: s.content,
        type: 'speech',
        target: s.target ?? undefined,
        subtext: mindReading && mind ? mind.inner_thought : undefined,
      })
    }

    // Whisper notices
    for (const w of tick.public.whispers) {
      const fromName = sceneFile.participant_names[w.from] ?? ''
      const toName = sceneFile.participant_names[w.to] ?? ''
      bubbles.push({
        agentId: w.from,
        displayName: fromName,
        text: mindReading
          ? `🤫 → ${toName}\n${w.content}`
          : `${fromName}对${toName}说了悄悄话`,
        type: 'whisper_notice',
        target: w.to,
        subtext: mindReading ? tick.minds[w.from]?.inner_thought : undefined,
      })
    }

    // Non-verbal actions (always shown for agents without a bubble)
    for (const [agentId, mind] of Object.entries(tick.minds)) {
      if (bubbles.some(b => b.agentId === agentId)) continue
      if (mind.action_type === 'non_verbal' && mind.action_content) {
        bubbles.push({
          agentId,
          displayName: '',
          text: mind.action_content,
          type: 'action',
        })
      }
    }

    // Mind-reading: emoji indicators for remaining observers
    if (mindReading) {
      for (const [agentId, mind] of Object.entries(tick.minds)) {
        if (bubbles.some(b => b.agentId === agentId)) continue
        bubbles.push({
          agentId,
          displayName: '',
          text: EMOTION_EMOJIS[mind.emotion] ?? '😐',
          subtext: mind.inner_thought,
          type: 'emoji',
        })
      }
    }

    bubbleRef.current?.setBubbles(bubbles)

    // Danmu in broadcast mode
    if (mode === 'broadcast' && prevTickRef.current !== currentTick) {
      const danmuTexts = pickDanmu(tick)
      if (danmuTexts.length > 0) danmuRef.current?.fire(danmuTexts)
    }
    prevTickRef.current = currentTick
  }, [sceneFile, groupIdx, currentTick, mindReading, focusedAgent, mode])

  // Camera: fit to room when room changes
  useEffect(() => {
    const room = ROOMS[currentRoom]
    const cam = cameraRef.current
    if (!room || !cam) return
    cam.fitToRoom(room.cols * TILE, room.rows * TILE, UI_INSET)
  }, [currentRoom])

  // ResizeObserver: keep canvas + camera in sync with viewport
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

  // Ticker: update camera + bubble positions
  useTick(() => {
    cameraRef.current?.update()
    if (worldRef.current) {
      bubbleRef.current?.updatePositions(spritesRef.current, worldRef.current)
    }
  })

  // Mouse handlers for explore mode camera
  useEffect(() => {
    const canvas = app.canvas as HTMLCanvasElement
    const cam = cameraRef.current
    if (!cam || mode !== 'explore') return

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
  }, [app, mode])

  // Keyboard controls
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const store = useWorldStore.getState()
      if (e.key === 'ArrowRight') store.advanceTick()
      else if (e.key === 'ArrowLeft') store.retreatTick()
      else if (e.key === ' ') { e.preventDefault(); store.setIsPlaying(!store.isPlaying) }
      else if (e.key === 'm' || e.key === 'M') store.toggleMindReading()
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

  useEffect(() => {
    playbackController.start()
    return () => playbackController.stop()
  }, [])

  return (
    <div className="w-screen h-screen bg-[#1a1a2e] overflow-hidden relative">
      <div className="w-full h-full">
        <Application
          width={window.innerWidth}
          height={window.innerHeight}
          background={0x1a1a2e}
          antialias={false}
          resolution={1}
        >
          <WorldScene />
        </Application>
      </div>

      {/* React UI overlays */}
      <TopBar />
      <BottomBar />
      <RoomNav />
      <ErrorBoundary><SidePanel /></ErrorBoundary>
      <GodModeChat />
      <RolePlayChat />
    </div>
  )
}

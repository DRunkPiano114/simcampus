import { create } from 'zustand'
import type { RoomId, SceneIndexEntry, SceneFile, Meta, SceneGroup } from '../lib/types'
import type { ChatMessage, AgentReaction } from '../lib/chat'
import { findFirstSpeechTick, findLastSpeechTick } from '../components/narrative/focal'

type Landing = 'start' | 'end'

export type ChatMode = 'off' | 'god' | 'roleplay'

interface WorldState {
  // --- data ---
  meta: Meta | null
  scenes: SceneIndexEntry[]
  currentSceneFile: SceneFile | null

  // --- navigation ---
  currentDay: string
  currentSceneIndex: number
  activeGroupIndex: number
  currentTick: number
  currentRoom: RoomId
  // Where to land after the next async unit load. Reset to 'start' on consumption.
  // A rewind (←) sets these to 'end' so the just-loaded scene/day lands on its
  // last group/tick instead of its first.
  pendingSceneLanding: Landing
  pendingDayLanding: Landing

  // --- focus ---
  focusedAgent: string | null
  sidePanelOpen: boolean

  // --- chat ---
  chatMode: ChatMode
  chatMessages: ChatMessage[]
  chatStreaming: boolean
  chatStreamBuffer: string
  rolePlayUserAgent: string | null
  rolePlayTargetAgents: string[]
  rolePlayReactions: AgentReaction[]

  // --- actions ---
  setMeta: (meta: Meta) => void
  setScenes: (scenes: SceneIndexEntry[]) => void
  setCurrentSceneFile: (file: SceneFile | null) => void
  setCurrentDay: (day: string, landAtEnd?: boolean) => void
  setCurrentSceneIndex: (index: number, landAtEnd?: boolean) => void
  setActiveGroupIndex: (index: number) => void
  setCurrentTick: (tick: number) => void
  setCurrentRoom: (room: RoomId) => void
  consumePendingDayLanding: () => Landing
  setFocusedAgent: (agentId: string | null) => void
  setSidePanelOpen: (open: boolean) => void
  advanceTick: () => void
  retreatTick: () => void
  goNext: () => void
  goPrev: () => void

  // --- chat actions ---
  openGodModeChat: (agentId: string) => void
  openRolePlayChat: (userAgentId: string, targets: string[]) => void
  closeChat: () => void
  appendChatMessage: (msg: ChatMessage) => void
  setChatStreaming: (streaming: boolean) => void
  appendStreamToken: (token: string) => void
  flushStreamBuffer: () => void
  appendAgentReaction: (reaction: AgentReaction) => void
}

export const useWorldStore = create<WorldState>((set, get) => ({
  meta: null,
  scenes: [],
  currentSceneFile: null,

  currentDay: 'day_001',
  currentSceneIndex: 0,
  activeGroupIndex: 0,
  currentTick: 0,
  currentRoom: '教室',
  pendingSceneLanding: 'start',
  pendingDayLanding: 'start',

  focusedAgent: null,
  sidePanelOpen: false,

  chatMode: 'off',
  chatMessages: [],
  chatStreaming: false,
  chatStreamBuffer: '',
  rolePlayUserAgent: null,
  rolePlayTargetAgents: [],
  rolePlayReactions: [],

  setMeta: (meta) => set({ meta }),
  setScenes: (scenes) => set({ scenes }),

  setCurrentSceneFile: (file) => {
    if (!file) {
      set({ currentSceneFile: null, currentTick: 0 })
      return
    }
    const { pendingSceneLanding } = get()
    if (pendingSceneLanding === 'end') {
      const lastIdx = Math.max(0, file.groups.length - 1)
      const lastGroup = file.groups[lastIdx]
      set({
        currentSceneFile: file,
        activeGroupIndex: lastIdx,
        currentTick: findLastSpeechTick(lastGroup),
        pendingSceneLanding: 'start',
      })
    } else {
      const firstGroup = file.groups[0]
      set({
        currentSceneFile: file,
        activeGroupIndex: 0,
        currentTick: findFirstSpeechTick(firstGroup),
        pendingSceneLanding: 'start',
      })
    }
  },

  setCurrentDay: (day, landAtEnd = false) => set({
    currentDay: day,
    currentSceneIndex: 0,
    activeGroupIndex: 0,
    currentTick: 0,
    pendingDayLanding: landAtEnd ? 'end' : 'start',
    pendingSceneLanding: landAtEnd ? 'end' : 'start',
  }),

  setCurrentSceneIndex: (index, landAtEnd = false) => {
    const { scenes } = get()
    const scene = scenes[index]
    set({
      currentSceneIndex: index,
      activeGroupIndex: 0,
      currentTick: 0,
      currentRoom: (scene?.location as RoomId) ?? '教室',
      pendingSceneLanding: landAtEnd ? 'end' : 'start',
    })
  },

  consumePendingDayLanding: () => {
    const { pendingDayLanding } = get()
    if (pendingDayLanding === 'end') set({ pendingDayLanding: 'start' })
    return pendingDayLanding
  },

  setActiveGroupIndex: (index) => {
    const file = get().currentSceneFile
    const group = file?.groups[index]
    set({
      activeGroupIndex: index,
      currentTick: findFirstSpeechTick(group),
    })
  },

  setCurrentTick: (tick) => set({ currentTick: tick }),
  setCurrentRoom: (room) => set({ currentRoom: room }),

  setFocusedAgent: (agentId) => set({
    focusedAgent: agentId,
    sidePanelOpen: agentId !== null,
  }),

  setSidePanelOpen: (open) => set({
    sidePanelOpen: open,
    focusedAgent: open ? get().focusedAgent : null,
  }),

  advanceTick: () => {
    const { currentTick, currentSceneFile, activeGroupIndex } = get()
    if (!currentSceneFile) return
    const group = currentSceneFile.groups[activeGroupIndex]
    if (!group || group.is_solo) return
    const maxTick = group.ticks.length - 1
    if (currentTick < maxTick) {
      set({ currentTick: currentTick + 1 })
    }
  },

  retreatTick: () => {
    const { currentTick } = get()
    if (currentTick > 0) {
      set({ currentTick: currentTick - 1 })
    }
  },

  // Cross-group / cross-scene navigation. At a tick boundary, jumps to the
  // adjacent group (first speech tick) or scene (group 0, first speech tick),
  // so ←/→ never gets stuck mid-conversation.
  goNext: () => {
    const { currentTick, currentSceneFile, activeGroupIndex, scenes, currentSceneIndex, currentDay, meta } = get()
    if (!currentSceneFile) return
    const group = currentSceneFile.groups[activeGroupIndex]
    const ticks = group && !group.is_solo ? (group as SceneGroup).ticks : []
    if (ticks.length > 0 && currentTick < ticks.length - 1) {
      set({ currentTick: currentTick + 1 })
      return
    }
    if (activeGroupIndex < currentSceneFile.groups.length - 1) {
      const next = currentSceneFile.groups[activeGroupIndex + 1]
      set({ activeGroupIndex: activeGroupIndex + 1, currentTick: findFirstSpeechTick(next) })
      return
    }
    if (currentSceneIndex < scenes.length - 1) {
      get().setCurrentSceneIndex(currentSceneIndex + 1)
      return
    }
    const days = meta?.days ?? []
    const dayIdx = days.indexOf(currentDay)
    if (dayIdx >= 0 && dayIdx < days.length - 1) {
      get().setCurrentDay(days[dayIdx + 1])
    }
  },

  // Rewinding across a unit boundary lands on the LAST tick of the previous
  // unit (not the first), giving a "continuing backward" feel. Day boundaries
  // roll over into the previous day's last scene / last group / last tick.
  goPrev: () => {
    const { currentTick, currentSceneFile, activeGroupIndex, currentSceneIndex, currentDay, meta } = get()
    if (!currentSceneFile) return
    if (currentTick > 0) {
      set({ currentTick: currentTick - 1 })
      return
    }
    if (activeGroupIndex > 0) {
      const prev = currentSceneFile.groups[activeGroupIndex - 1]
      set({ activeGroupIndex: activeGroupIndex - 1, currentTick: findLastSpeechTick(prev) })
      return
    }
    if (currentSceneIndex > 0) {
      get().setCurrentSceneIndex(currentSceneIndex - 1, true)
      return
    }
    const days = meta?.days ?? []
    const dayIdx = days.indexOf(currentDay)
    if (dayIdx > 0) {
      get().setCurrentDay(days[dayIdx - 1], true)
    }
  },

  // --- chat actions ---
  openGodModeChat: (agentId) => set({
    chatMode: 'god',
    chatMessages: [],
    chatStreaming: false,
    chatStreamBuffer: '',
    focusedAgent: agentId,
    sidePanelOpen: false,
    rolePlayReactions: [],
  }),

  openRolePlayChat: (userAgentId, targets) => set({
    chatMode: 'roleplay',
    chatMessages: [],
    chatStreaming: false,
    chatStreamBuffer: '',
    rolePlayUserAgent: userAgentId,
    rolePlayTargetAgents: targets,
    rolePlayReactions: [],
  }),

  closeChat: () => set({
    chatMode: 'off',
    chatMessages: [],
    chatStreaming: false,
    chatStreamBuffer: '',
    rolePlayUserAgent: null,
    rolePlayTargetAgents: [],
    rolePlayReactions: [],
  }),

  appendChatMessage: (msg) => set((s) => ({
    chatMessages: [...s.chatMessages, msg],
  })),

  setChatStreaming: (streaming) => set({ chatStreaming: streaming }),

  appendStreamToken: (token) => set((s) => ({
    chatStreamBuffer: s.chatStreamBuffer + token,
  })),

  flushStreamBuffer: () => {
    const { chatStreamBuffer } = get()
    if (!chatStreamBuffer) return
    set((s) => ({
      chatMessages: [...s.chatMessages, {
        role: 'assistant',
        content: chatStreamBuffer,
      }],
      chatStreamBuffer: '',
    }))
  },

  appendAgentReaction: (reaction) => set((s) => ({
    rolePlayReactions: [...s.rolePlayReactions, reaction],
    chatMessages: [...s.chatMessages, {
      role: reaction.agent_id,
      content: reaction.content,
      agent_name: reaction.agent_name,
    }],
  })),
}))

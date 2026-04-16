import type { Tick, SceneGroup, MindState } from '../../lib/types'

export type FocalKind = 'speaker' | 'non_verbal' | 'observation'

export interface Focal {
  kind: FocalKind
  agentId: string
  target?: string | null
  content?: string
}

/**
 * Pick the focal agent for a tick.
 * - Speaker (if any) always wins — public speech has authoritative clarity.
 * - Otherwise: any disruptive non-speaker, then highest-urgency non_verbal,
 *   then highest-urgency observation, falling back to the first participant.
 */
export function pickFocal(tick: Tick, group: SceneGroup): Focal {
  if (tick.public.speech) {
    const s = tick.public.speech
    return { kind: 'speaker', agentId: s.agent, target: s.target, content: s.content }
  }

  const mindEntries = Object.entries(tick.minds)

  const disruptive = mindEntries.find(([, m]) => m.is_disruptive)
  if (disruptive) {
    return {
      kind: 'non_verbal',
      agentId: disruptive[0],
      content: disruptive[1].action_content ?? disruptive[1].inner_thought,
    }
  }

  const nonVerbal = mindEntries
    .filter(([, m]) => m.action_type === 'non_verbal' && m.action_content)
    .sort((a, b) => b[1].urgency - a[1].urgency)
  if (nonVerbal[0]) {
    return {
      kind: 'non_verbal',
      agentId: nonVerbal[0][0],
      content: nonVerbal[0][1].action_content ?? undefined,
    }
  }

  const topUrgency = [...mindEntries].sort((a, b) => b[1].urgency - a[1].urgency)[0]
  return {
    kind: 'observation',
    agentId: topUrgency?.[0] ?? group.participants[0],
    content: topUrgency?.[1].inner_thought,
  }
}

/**
 * Non-focal observers, sorted is_disruptive DESC → urgency DESC.
 * `tick.minds` already excludes gated agents (backend serializer),
 * so we only filter out the focal agent here.
 */
export function partitionObservers(
  tick: Tick,
  focalAgentId: string,
): Array<[string, MindState]> {
  return Object.entries(tick.minds)
    .filter(([id]) => id !== focalAgentId)
    .sort(([, a], [, b]) => {
      if (a.is_disruptive !== b.is_disruptive) return a.is_disruptive ? -1 : 1
      return b.urgency - a.urgency
    })
}

/**
 * First tick in a group that contains a public speech. Fallback 0.
 * Solo groups have no ticks, so return 0.
 */
export function findFirstSpeechTick(group: { is_solo?: boolean; ticks?: Tick[] } | undefined): number {
  if (!group || group.is_solo || !group.ticks) return 0
  const idx = group.ticks.findIndex(t => t.public?.speech != null)
  return idx >= 0 ? idx : 0
}

/**
 * Last tick in a group. Used when rewinding across a boundary so the
 * previous unit lands on its final tick (gives the "connected" feel of
 * continuing backward in time rather than restarting a unit).
 */
export function findLastSpeechTick(group: { is_solo?: boolean; ticks?: Tick[] } | undefined): number {
  if (!group || group.is_solo || !group.ticks || group.ticks.length === 0) return 0
  return group.ticks.length - 1
}

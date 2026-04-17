import { useWorldStore } from '../../stores/useWorldStore'
import { EMOTION_COLORS, EMOTION_LABELS } from '../../lib/constants'
import { ShareButtons } from './ShareButtons'
import type { Tick, Emotion, MindState, GroupData } from '../../lib/types'

const URGENCY_THRESHOLD = 2

export function GroupGrid() {
  const sceneFile = useWorldStore(s => s.currentSceneFile)
  const groupIdx = useWorldStore(s => s.activeGroupIndex)
  const currentTick = useWorldStore(s => s.currentTick)
  const currentDay = useWorldStore(s => s.currentDay)
  const currentSceneIndex = useWorldStore(s => s.currentSceneIndex)

  if (!sceneFile) {
    return <div className="grid-stage grid-loading">…</div>
  }

  const group = sceneFile.groups[groupIdx]
  const names = sceneFile.participant_names

  // day_001 → 1; the API uses a bare integer.
  const dayNum = parseInt(currentDay.replace('day_', ''), 10)
  const cardEndpoint = `/api/card/scene/${dayNum}/${currentSceneIndex}`
  // Pin the share card to the viewer's current group so the caption + image
  // match what they're looking at. Solo groups have no scene card — omit the
  // param so the server falls back to its featured multi-agent pick instead
  // of 404'ing the share buttons.
  const shareGroupQuery = group && !group.is_solo ? `group=${groupIdx}` : undefined

  return (
    <div className="grid-stage">
      <div className="grid-page">
        <GroupPills groups={sceneFile.groups} activeIdx={groupIdx} names={names} />
        <GroupBody group={group} currentTick={currentTick} names={names} />
        <ShareButtons
          cardEndpoint={cardEndpoint}
          cardLabel="场景卡"
          endpointQuery={shareGroupQuery}
        />
      </div>
    </div>
  )
}

interface GroupPillsProps {
  groups: GroupData[]
  activeIdx: number
  names: Record<string, string>
}

function GroupPills({ groups, activeIdx, names }: GroupPillsProps) {
  const setActiveGroup = useWorldStore(s => s.setActiveGroupIndex)
  return (
    <nav className="group-pills">
      {groups.map((g, idx) => {
        const label = g.is_solo
          ? (names[g.participants[0]] ?? g.participants[0])
          : g.participants.map(p => names[p] ?? p).join(' · ')
        const prefix = g.is_solo ? '独白' : `G${g.group_index}`
        return (
          <button
            key={idx}
            type="button"
            onClick={() => setActiveGroup(idx)}
            className={`group-pill${idx === activeIdx ? ' group-pill-active' : ''}`}
          >
            <span className="group-pill-prefix">{prefix}</span>
            <span className="group-pill-names">{label}</span>
          </button>
        )
      })}
    </nav>
  )
}

interface GroupBodyProps {
  group: GroupData | undefined
  currentTick: number
  names: Record<string, string>
}

function GroupBody({ group, currentTick, names }: GroupBodyProps) {
  if (!group) {
    return <div className="grid-empty">（无内容）</div>
  }

  if (group.is_solo) {
    const aid = group.participants[0]
    return (
      <div className={`grid-cards ${gridClassFor(1)}`}>
        <CharacterCard
          agentId={aid}
          displayName={names[aid] ?? aid}
          isSpeaker={false}
          speech={null}
          thought={group.solo_reflection.inner_thought}
          emotion={group.solo_reflection.emotion}
          actionContent={group.solo_reflection.activity || null}
          vertical={false}
        />
      </div>
    )
  }

  const ticks = group.ticks
  const tickIdx = Math.min(currentTick, ticks.length - 1)
  const tick: Tick | undefined = ticks[tickIdx]

  if (!tick) {
    return <div className="grid-empty">（场景过渡中…）</div>
  }

  const speakerId = tick.public.speech?.agent ?? null
  const targetId = tick.public.speech?.target ?? null
  const n = group.participants.length
  const vertical = n >= 4

  return (
    <>
      <div className={`grid-cards ${gridClassFor(n)}`}>
        {group.participants.map(aid => {
          const mind = tick.minds[aid]
          const isSpeaker = aid === speakerId
          const isTarget = aid === targetId
          const passes = isSpeaker || isTarget || mindPassesFilter(mind)
          const speechContent = isSpeaker ? tick.public.speech?.content ?? null : null
          const thought = mind?.inner_thought && passes ? mind.inner_thought : null
          const actionContent = !isSpeaker ? actionContentFor(aid, tick, mind) : null
          return (
            <CharacterCard
              key={aid}
              agentId={aid}
              displayName={names[aid] ?? aid}
              isSpeaker={isSpeaker}
              speech={speechContent}
              thought={thought}
              emotion={mind?.emotion}
              actionContent={actionContent}
              vertical={vertical}
            />
          )
        })}
      </div>
      <TickNav current={tickIdx + 1} total={ticks.length} />
    </>
  )
}

// Fixed-position adaptive grid — each participant owns a stable cell that
// doesn't change per tick. Size scales with group count so everyone fits
// without panel scroll.
function gridClassFor(n: number): string {
  if (n <= 1) return 'grid-cards-n1'
  if (n === 2) return 'grid-cards-n2'
  if (n === 3) return 'grid-cards-n3'
  if (n === 4) return 'grid-cards-n4'
  if (n <= 6) return 'grid-cards-n6'
  return 'grid-cards-n9'
}

function mindPassesFilter(mind: MindState | undefined): boolean {
  if (!mind) return false
  return mind.is_disruptive || mind.urgency >= URGENCY_THRESHOLD
}

function actionContentFor(
  agentId: string,
  tick: Tick,
  mind: MindState | undefined,
): string | null {
  const pub = tick.public.actions.find(a => a.agent === agentId)
  if (pub?.content) return pub.content
  if (mind && mind.action_type !== 'speak' && mind.action_content) {
    return mind.action_content
  }
  return null
}

interface CharacterCardProps {
  agentId: string
  displayName: string
  isSpeaker: boolean
  speech: string | null
  thought: string | null
  emotion: Emotion | undefined
  actionContent: string | null
  vertical: boolean
}

function CharacterCard({
  agentId,
  displayName,
  isSpeaker,
  speech,
  thought,
  emotion,
  actionContent,
  vertical,
}: CharacterCardProps) {
  const setFocusedAgent = useWorldStore(s => s.setFocusedAgent)

  const headerContent = (
    <>
      <button
        className="char-card-name"
        onClick={() => setFocusedAgent(agentId)}
        type="button"
      >
        {displayName}
      </button>
      {emotion && <span className="char-card-emotion">{EMOTION_LABELS[emotion]}</span>}
      {isSpeaker && <span className="char-card-speak-label">说</span>}
    </>
  )

  // Body holds the "发声层" only. If not speaking, body is intentionally empty —
  // the whitespace is the silence indicator, no text placeholder needed.
  const bodyContent = speech ? (
    <div className="char-card-speech">“{speech}”</div>
  ) : null

  // Footer is the "内部 + 物理层": thought bubble on top, action line below.
  // Pinned to the bottom of the card via flex layout. A 1px divider separates
  // it from the speech above when both are present.
  const hasFooter = Boolean(thought || actionContent)
  const footerClass = `char-card-footer${speech ? ' char-card-footer-sep' : ''}`
  const footerContent = hasFooter ? (
    <div className={footerClass}>
      {thought && (
        <div className="char-card-thought">
          <span className="char-card-tag tag-thought">心</span>
          {thought}
        </div>
      )}
      {actionContent && (
        <div className="char-card-action-line">
          <span className="char-card-action-dot">○</span>
          {actionContent}
        </div>
      )}
    </div>
  ) : null

  const className = `char-card${vertical ? ' char-card-vertical' : ' char-card-horizontal'}${isSpeaker ? ' char-card-speaker' : ''}`

  // Emotion strip on the card's left edge — instant group-level emotional read.
  const cardStyle = emotion
    ? ({ '--emotion-color': EMOTION_COLORS[emotion] } as React.CSSProperties)
    : undefined

  if (vertical) {
    return (
      <div className={className} style={cardStyle}>
        <div className="char-card-head">
          <Avatar agentId={agentId} displayName={displayName} talking={isSpeaker} />
          <div className="char-card-meta">{headerContent}</div>
        </div>
        <div className="char-card-body">{bodyContent}</div>
        {footerContent}
      </div>
    )
  }

  return (
    <div className={className} style={cardStyle}>
      <Avatar agentId={agentId} displayName={displayName} talking={isSpeaker} />
      <div className="char-card-content">
        <div className="char-card-head">{headerContent}</div>
        <div className="char-card-body">{bodyContent}</div>
        {footerContent}
      </div>
    </div>
  )
}

interface AvatarProps {
  agentId: string
  displayName: string
  talking: boolean
}

function Avatar({ agentId, displayName, talking }: AvatarProps) {
  return (
    <div className={`avatar${talking ? ' avatar-talking' : ''}`}>
      <img
        className="avatar-sprite"
        src={`/data/map_sprites/${agentId}.png`}
        alt={displayName}
        draggable={false}
      />
    </div>
  )
}

function TickNav({ current, total }: { current: number; total: number }) {
  const goPrev = useWorldStore(s => s.goPrev)
  const goNext = useWorldStore(s => s.goNext)
  return (
    <div className="grid-tick-nav">
      <button onClick={goPrev} type="button">◀</button>
      <span>{current} / {total}</span>
      <button onClick={goNext} type="button">▶</button>
    </div>
  )
}

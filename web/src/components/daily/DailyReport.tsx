import { useEffect, useState, useMemo } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { loadMeta } from '../../lib/data'
import { EMOTION_LABELS, LOCATION_ICONS } from '../../lib/constants'
import { ShareButtons } from '../narrative/ShareButtons'
import type { Emotion } from '../../lib/types'

interface Beat {
  scene_time: string
  scene_name: string
  scene_location: string
  scene_file: string
  group_index: number
  tick_index: number
  speaker_id: string
  speaker_name: string
  speech: string | null
  thought_id: string | null
  thought_name: string | null
  thought: string | null
  urgency: number
}

interface MoodEntry {
  agent_id: string
  agent_name: string
  dominant_emotion: Emotion
  emotion_counts: Record<string, number>
  main_color: string
  motif_emoji: string
}

interface CP {
  a_id: string
  a_name: string
  b_id: string
  b_name: string
  favorability_delta: number
  trust_delta: number
  understanding_delta: number
}

interface GoldenQuote {
  agent_id: string
  agent_name: string
  text: string
  scene_time: string
  scene_name: string
}

interface SceneThumb {
  time: string
  name: string
  location: string
  file: string
  participants: string[]
}

interface DailySummaryJson {
  day: number
  headline: Beat | null
  secondaries: Beat[]
  mood_map: MoodEntry[]
  cp: CP | null
  golden_quote: GoldenQuote | null
  scene_thumbs: SceneThumb[]
  caption_payload: {
    caption: string
    hashtags: string[]
    filename: string
  }
}

// Entry route `/` — decide the latest day, then redirect.
export function DailyReportHome() {
  const [dayId, setDayId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadMeta()
      .then(m => {
        const latest = m.days[m.days.length - 1]
        setDayId(latest || 'day_001')
      })
      .catch(e => setError(String(e)))
  }, [])

  if (error) return <div className="daily-root daily-error">数据加载失败：{error}</div>
  if (!dayId) return <div className="daily-root daily-loading">加载中…</div>
  return <Navigate to={`/day/${dayId}`} replace />
}

export function DailyReport() {
  const { dayId } = useParams<{ dayId: string }>()
  const day = useMemo(() => {
    if (!dayId) return null
    const m = dayId.match(/day_0*(\d+)/)
    return m ? parseInt(m[1], 10) : null
  }, [dayId])

  const [summary, setSummary] = useState<DailySummaryJson | null>(null)
  const [loading, setLoading] = useState(true)
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)
  const [days, setDays] = useState<string[] | null>(null)

  useEffect(() => {
    loadMeta().then(m => setDays(m.days)).catch(() => setDays(null))
  }, [])

  useEffect(() => {
    if (day === null) return
    let alive = true
    setLoading(true)
    setSummary(null)
    fetch(`/api/card/daily/${day}.json`)
      .then(async r => {
        if (!alive) return
        if (!r.ok) {
          setApiOnline(false)
          setLoading(false)
          return
        }
        setApiOnline(true)
        setSummary(await r.json())
        setLoading(false)
      })
      .catch(() => {
        if (alive) {
          setApiOnline(false)
          setLoading(false)
        }
      })
    return () => { alive = false }
  }, [day])

  if (!dayId || day === null) {
    return <div className="daily-root daily-error">无效的日期：{dayId}</div>
  }

  return (
    <div className="daily-root">
      <Link
        to={`/day/${dayId}/scene/first`}
        className="seal-btn seal-btn--gold seal-btn-pinned"
        aria-label="现场 — 进入场景视图"
        title="现场 — 进入场景视图"
      >
        <span className="seal-btn-text">现场</span>
      </Link>

      <DailyNav dayId={dayId} days={days} />

      {loading && <div className="daily-loading">加载今日日报中…</div>}

      {!loading && apiOnline === false && (
        <div className="daily-offline">
          <p>API 未启动，无法生成今日日报。</p>
          <p className="daily-offline-cmd">请先执行 <code>uv run api</code>。</p>
          <Link to={`/day/${dayId}/scene/first`} className="daily-offline-fallback">
            进入场景视图（不需要 API）→
          </Link>
        </div>
      )}

      {!loading && summary && (
        <>
          <DailyHero day={summary.day} />
          <div className="daily-actions">
            <ShareButtons cardEndpoint={`/api/card/daily/${summary.day}`} cardLabel="今日日报" />
          </div>
          <div className="daily-body">
            <div className="daily-col daily-col-left">
              {summary.headline && <DailyHeadline headline={summary.headline} dayId={dayId} />}
              {summary.golden_quote && <DailyQuote quote={summary.golden_quote} />}
              <DailySecondaries beats={summary.secondaries} dayId={dayId} />
            </div>
            <div className="daily-col daily-col-right">
              <MoodMap entries={summary.mood_map} />
              {summary.cp && <CPTracker cp={summary.cp} />}
              <SceneStrip thumbs={summary.scene_thumbs} dayId={dayId} />
            </div>
          </div>
          <div className="daily-footer-link">
            <Link to={`/characters/day/${dayId}`}>人物志 →</Link>
          </div>
        </>
      )}
    </div>
  )
}

// --- Sub-components --------------------------------------------------------

function DailyNav({ dayId, days }: { dayId: string; days: string[] | null }) {
  if (!days) {
    return (
      <nav className="daily-nav">
        <span className="daily-nav-label">班级日报</span>
      </nav>
    )
  }
  const idx = days.indexOf(dayId)
  const prev = idx > 0 ? days[idx - 1] : null
  const next = idx >= 0 && idx < days.length - 1 ? days[idx + 1] : null
  return (
    <nav className="daily-nav">
      <div className="daily-nav-left">
        {prev ? (
          <Link to={`/day/${prev}`} className="daily-nav-btn">◀ 昨日</Link>
        ) : (
          <span className="daily-nav-btn daily-nav-btn-disabled">◀ 昨日</span>
        )}
      </div>
      <span className="daily-nav-label">班级日报</span>
      <div className="daily-nav-right">
        {next ? (
          <Link to={`/day/${next}`} className="daily-nav-btn">明日 ▶</Link>
        ) : (
          <span className="daily-nav-btn daily-nav-btn-disabled">明日 ▶</span>
        )}
      </div>
    </nav>
  )
}

function DailyHero({ day }: { day: number }) {
  return (
    <header className="daily-hero">
      <div className="daily-hero-seal">第{String(day).padStart(3, '0')}天</div>
      <h1 className="daily-hero-title">班级日报</h1>
      <p className="daily-hero-subtitle">一天里的教室、宿舍、操场与心事</p>
    </header>
  )
}

function DailyHeadline({ headline, dayId }: { headline: Beat; dayId: string }) {
  return (
    <section className="daily-section daily-headline">
      <h2 className="daily-section-title">今日头条</h2>
      <div className="daily-headline-meta">
        {headline.scene_time} · {headline.scene_name} · {LOCATION_ICONS[headline.scene_location] ?? ''} {headline.scene_location}
      </div>
      {headline.speech && (
        <div className="daily-speech">
          <span className="daily-speech-speaker">{headline.speaker_name}</span>
          <span className="daily-speech-text">"{headline.speech}"</span>
        </div>
      )}
      {headline.thought && (
        <div className="daily-thought">
          <span className="daily-thought-label">（{headline.thought_name} 心想）</span>
          <span className="daily-thought-text">{headline.thought}</span>
        </div>
      )}
      <div className="daily-headline-link">
        <Link to={`/day/${dayId}/scene/${headline.scene_file}`}>
          进入现场 →
        </Link>
      </div>
    </section>
  )
}

function DailyQuote({ quote }: { quote: GoldenQuote }) {
  return (
    <section className="daily-section daily-quote-section">
      <h2 className="daily-section-title">今日金句</h2>
      <blockquote className="daily-quote">
        <span className="daily-quote-text">{quote.text}</span>
        <footer className="daily-quote-footer">
          — {quote.agent_name} · {quote.scene_time} {quote.scene_name}
        </footer>
      </blockquote>
    </section>
  )
}

function DailySecondaries({ beats, dayId }: { beats: Beat[]; dayId: string }) {
  if (beats.length === 0) return null
  return (
    <section className="daily-section daily-secondaries">
      <h2 className="daily-section-title">次条</h2>
      <ul className="daily-secondary-list">
        {beats.map((b, i) => (
          <li key={i} className="daily-secondary-item">
            <Link to={`/day/${dayId}/scene/${b.scene_file}`} className="daily-secondary-link">
              <span className="daily-secondary-meta">
                {b.scene_time} · {b.scene_name}@{b.scene_location}
              </span>
              <span className="daily-secondary-body">
                {b.speech
                  ? `${b.speaker_name}：${b.speech}`
                  : b.thought
                    ? `（${b.thought_name} 心想）${b.thought}`
                    : '（静默）'}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

function MoodMap({ entries }: { entries: MoodEntry[] }) {
  if (entries.length === 0) return null
  return (
    <section className="daily-section daily-mood-map">
      <h2 className="daily-section-title">心情地图</h2>
      <ul className="mood-grid">
        {entries.map(e => (
          <li key={e.agent_id} className="mood-cell">
            <img
              className="mood-sprite"
              src={`/data/map_sprites/${e.agent_id}.png`}
              alt=""
              aria-hidden
            />
            <div className="mood-name">{e.agent_name}</div>
            <div className="mood-emotion">
              {e.motif_emoji} {EMOTION_LABELS[e.dominant_emotion] ?? e.dominant_emotion}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function CPTracker({ cp }: { cp: CP }) {
  return (
    <section className="daily-section daily-cp">
      <h2 className="daily-section-title">今日 CP</h2>
      <div className="cp-row">
        <div className="cp-name">{cp.a_name}</div>
        <div className="cp-heart" aria-hidden>♥</div>
        <div className="cp-name">{cp.b_name}</div>
      </div>
      <div className="cp-deltas">
        <span>好感 +{cp.favorability_delta}</span>
        <span>信任 +{cp.trust_delta}</span>
        <span>理解 +{cp.understanding_delta}</span>
      </div>
    </section>
  )
}

function SceneStrip({ thumbs, dayId }: { thumbs: SceneThumb[]; dayId: string }) {
  if (thumbs.length === 0) return null
  return (
    <section className="daily-section daily-scene-strip">
      <h2 className="daily-section-title">今日场景</h2>
      <ul className="scene-strip-list">
        {thumbs.map((t, i) => (
          <li key={i} className="scene-strip-item">
            <Link to={`/day/${dayId}/scene/${t.file}`} className="scene-strip-link">
              <div className="scene-strip-icon">
                {LOCATION_ICONS[t.location] ?? '📍'}
              </div>
              <div className="scene-strip-meta">
                <div className="scene-strip-time">{t.time}</div>
                <div className="scene-strip-name">{t.name}</div>
                <div className="scene-strip-loc">{t.location}</div>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

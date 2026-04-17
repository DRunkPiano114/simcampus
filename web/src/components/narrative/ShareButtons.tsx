import { useEffect, useState, type RefObject } from 'react'

interface ShareCardMeta {
  caption: string
  hashtags: string[]
  filename: string
  group_index?: number
}

type ApiStatus = 'unknown' | 'online' | 'offline' | 'not_available'

export interface ShareButtonsProps {
  /** Card endpoint base — e.g. `/api/card/scene/1/0`. Appends `.png` / `.json`. */
  cardEndpoint: string
  /** Human label for the card type, used in tooltips and toasts. */
  cardLabel?: string
  /** Set to false on surfaces where only the image is meaningful (e.g. the
   * daily report, where the long-form body *is* the caption). */
  showCopy?: boolean
  /** When set, save-image screenshots this DOM subtree instead of fetching
   * the server-rendered `.png`. Elements with `data-exclude-from-capture`
   * are skipped — use it to hide nav chrome and the share dock itself.
   * Metadata (caption / filename) still comes from `cardEndpoint.json`. */
  captureTarget?: RefObject<HTMLElement | null>
  /** Optional query string (no leading `?`) appended after the `.json` / `.png`
   * suffix. Used by the scene card to pass the currently active group so the
   * shared caption and image match what the viewer is looking at. */
  endpointQuery?: string
}

/**
 * Save PNG + copy caption to clipboard for any share card. Progressive:
 * falls back to download when Web Share API can't carry the file.
 *
 * Hidden when the API is offline — with no server there's nothing to render.
 * Matches the TopBar "入戏" grey-out pattern rather than inventing new UX.
 */
export function ShareButtons({
  cardEndpoint,
  cardLabel = '分享卡',
  showCopy = true,
  captureTarget,
  endpointQuery,
}: ShareButtonsProps) {
  const qs = endpointQuery ? `?${endpointQuery}` : ''
  const [healthStatus, setHealthStatus] = useState<'unknown' | 'online' | 'offline'>('unknown')
  const [cardStatus, setCardStatus] = useState<'unknown' | 'available' | 'not_available'>('unknown')
  const [toast, setToast] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [copying, setCopying] = useState(false)

  useEffect(() => {
    let alive = true
    const ctl = new AbortController()
    const timer = setTimeout(() => ctl.abort(), 1500)
    fetch('/api/health', { signal: ctl.signal })
      .then(r => { if (alive) setHealthStatus(r.ok ? 'online' : 'offline') })
      .catch(() => { if (alive) setHealthStatus('offline') })
      .finally(() => clearTimeout(timer))
    return () => { alive = false; ctl.abort(); clearTimeout(timer) }
  }, [])

  // Verify the specific card endpoint is available (404 when scene is all-solo).
  // Re-probes whenever the endpoint changes — user navigates between scenes.
  useEffect(() => {
    if (healthStatus !== 'online') {
      setCardStatus('unknown')
      return
    }
    let alive = true
    setCardStatus('unknown')
    fetch(`${cardEndpoint}.json${qs}`)
      .then(r => { if (alive) setCardStatus(r.ok ? 'available' : 'not_available') })
      .catch(() => { if (alive) setCardStatus('not_available') })
    return () => { alive = false }
  }, [cardEndpoint, qs, healthStatus])

  const apiStatus: ApiStatus =
    healthStatus === 'offline'
      ? 'offline'
      : healthStatus === 'unknown' || cardStatus === 'unknown'
        ? 'unknown'
        : cardStatus === 'available'
          ? 'online'
          : 'not_available'

  const flashToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2200)
  }

  async function fetchMeta(): Promise<ShareCardMeta | null> {
    try {
      const res = await fetch(`${cardEndpoint}.json${qs}`)
      if (!res.ok) return null
      return (await res.json()) as ShareCardMeta
    } catch {
      return null
    }
  }

  async function captureDomBlob(node: HTMLElement): Promise<Blob | null> {
    // Fonts must be ready or the screenshot falls back to the default font
    // and the Chinese glyphs look generic. Image loads are awaited too — any
    // pending sprite would render as a broken-image placeholder.
    if (document.fonts?.ready) {
      try { await document.fonts.ready } catch { /* ignore */ }
    }
    const imgs = Array.from(node.querySelectorAll('img'))
    await Promise.all(
      imgs.map(img => {
        if (img.complete && img.naturalWidth > 0) return Promise.resolve()
        return new Promise<void>(resolve => {
          img.addEventListener('load', () => resolve(), { once: true })
          img.addEventListener('error', () => resolve(), { once: true })
        })
      }),
    )
    const { toBlob } = await import('html-to-image')
    // Paper background matches `.daily-root` so antialiased edges don't show
    // a transparent halo when opened in viewers that default to white.
    // skipFonts: the page already rendered with the intended webfonts, so the
    // browser has them in its CSS cache; inlining Google Fonts' hundreds of
    // unicode-range WOFF2 subsets into the SVG takes ~10s for negligible
    // visual benefit on the capturing machine. Chinese glyphs fall back to
    // the system family in the rendered PNG (PingFang on macOS, YaHei on
    // Windows) — acceptable trade-off for a <1s save.
    return toBlob(node, {
      pixelRatio: 2,
      backgroundColor: '#f5efe0',
      skipFonts: true,
      filter: el => !(el instanceof HTMLElement && el.dataset.excludeFromCapture !== undefined),
    })
  }

  async function saveCard() {
    if (saving || apiStatus !== 'online') return
    setSaving(true)
    try {
      let blob: Blob | null
      let meta: ShareCardMeta | null
      if (captureTarget?.current) {
        // Client-side path: DOM screenshot. Metadata still comes from the
        // JSON endpoint so the filename and any future share text stay
        // server-owned.
        meta = await fetchMeta()
        try {
          blob = await captureDomBlob(captureTarget.current)
        } catch (err) {
          console.error('DOM capture failed', err)
          flashToast('截图失败')
          return
        }
        if (!blob) {
          flashToast('截图失败')
          return
        }
      } else {
        const [m, pngRes] = await Promise.all([
          fetchMeta(),
          fetch(`${cardEndpoint}.png${qs}`),
        ])
        if (!pngRes.ok) {
          flashToast('卡片生成失败')
          return
        }
        meta = m
        blob = await pngRes.blob()
      }
      const filename = meta?.filename ?? 'simcampus_card.png'

      // Progressive: Web Share API first (mobile native share sheet), then
      // download fallback (desktop). Image-only — captions belong to the
      // copy button; bundling them here makes the two actions feel identical
      // on platforms that merge share-sheet text with the attached file.
      const file = new File([blob], filename, { type: 'image/png' })
      if (typeof navigator.canShare === 'function' && navigator.canShare({ files: [file] })) {
        try {
          await navigator.share({ files: [file] })
          return
        } catch (err) {
          if (!(err instanceof DOMException) || err.name !== 'AbortError') {
            console.error('share failed, falling back to download', err)
          } else {
            return
          }
        }
      }

      const url = URL.createObjectURL(blob)
      const a = Object.assign(document.createElement('a'), { href: url, download: filename })
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      flashToast(`${cardLabel}已保存`)
    } finally {
      setSaving(false)
    }
  }

  async function copyCaption() {
    if (copying || apiStatus !== 'online') return
    setCopying(true)
    try {
      const meta = await fetchMeta()
      if (!meta) {
        flashToast('文案获取失败')
        return
      }
      const text = `${meta.caption}\n\n${meta.hashtags.join(' ')}`
      await navigator.clipboard.writeText(text)
      flashToast('文案已复制')
    } catch {
      flashToast('复制失败')
    } finally {
      setCopying(false)
    }
  }

  const disabled = apiStatus !== 'online'
  const title =
    apiStatus === 'unknown'
      ? '正在检查 API…'
      : apiStatus === 'online'
        ? ''
        : apiStatus === 'not_available'
          ? '该场景无对话，不生成场景卡'
          : '启动 API 服务后可用（uv run api）'

  return (
    <div className="share-dock">
      <div className="share-dock-label" aria-hidden>✂️ 把这一刻分享出去</div>
      <div className="share-buttons" role="group" aria-label="分享操作">
        <button
          type="button"
          className={`share-btn share-btn--primary${saving ? ' share-btn-busy' : ''}`}
          onClick={saveCard}
          disabled={disabled || saving}
          title={title || (saving ? '保存中…' : '保存图')}
        >
          <span className="share-btn-icon">📥</span>
          <span className="share-btn-label">{saving ? '保存中…' : '保存图'}</span>
        </button>
        {showCopy && (
          <button
            type="button"
            className={`share-btn share-btn--secondary${copying ? ' share-btn-busy' : ''}`}
            onClick={copyCaption}
            disabled={disabled || copying}
            title={title || (copying ? '复制中…' : '复制文案')}
          >
            <span className="share-btn-icon">📋</span>
            <span className="share-btn-label">{copying ? '复制中…' : '复制文案'}</span>
          </button>
        )}
        {toast && <div className="share-toast" role="status">{toast}</div>}
      </div>
    </div>
  )
}

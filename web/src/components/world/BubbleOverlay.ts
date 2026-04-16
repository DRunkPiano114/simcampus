import { Container } from 'pixi.js'

export interface BubbleData {
  agentId: string
  displayName: string
  text: string
  type: 'speech' | 'emoji' | 'action'
  target?: string
  /** For type:'emoji' only — emotion key used to pick the pixel balloon PNG
   * from /data/balloons/. Falls back to `text` (emoji glyph) if missing. */
  emotion?: string
}

/**
 * BubbleOverlay: imperative DOM overlay, synced with PixiJS Ticker.
 * Positions HTML bubbles above character sprites using world→screen projection.
 */
export class BubbleOverlay {
  private container: HTMLDivElement
  private elements = new Map<string, HTMLDivElement>()
  private onBubbleClick?: (agentId: string) => void

  constructor(parentEl: HTMLElement, onBubbleClick?: (agentId: string) => void) {
    this.onBubbleClick = onBubbleClick
    this.container = document.createElement('div')
    this.container.className = 'bubble-overlay'
    Object.assign(this.container.style, {
      position: 'absolute',
      inset: '0',
      pointerEvents: 'none',
      overflow: 'hidden',
    })
    parentEl.appendChild(this.container)
  }

  setBubbles(bubbles: BubbleData[]) {
    const activeIds = new Set(bubbles.map(b => b.agentId))
    for (const [id, el] of this.elements) {
      if (!activeIds.has(id)) {
        el.remove()
        this.elements.delete(id)
      }
    }

    for (const b of bubbles) {
      let el = this.elements.get(b.agentId)
      if (el && el.dataset.bubbleType !== b.type) {
        el.remove()
        this.elements.delete(b.agentId)
        el = undefined
      }
      if (!el) {
        el = this.createBubbleEl(b)
        this.container.appendChild(el)
        this.elements.set(b.agentId, el)
      }
      this.updateBubbleContent(el, b)
    }
  }

  updatePositions(
    sprites: Map<string, Container>,
    worldContainer: Container,
  ) {
    const cw = this.container.offsetWidth
    const ch = this.container.offsetHeight

    const updates: Array<{ el: HTMLDivElement; x: number; y: number; w: number; h: number }> = []
    for (const [agentId, el] of this.elements) {
      const sprite = sprites.get(agentId)
      if (!sprite) { el.style.display = 'none'; continue }

      const parent = worldContainer.parent
      if (!parent) { el.style.display = 'none'; continue }
      const global = sprite.toGlobal(parent)
      const isCompact = el.dataset.bubbleType === 'emoji' || el.dataset.bubbleType === 'action'
      updates.push({
        el,
        x: global.x,
        y: global.y - (isCompact ? 30 : 50),
        w: el.offsetWidth,
        h: el.offsetHeight,
      })
    }

    const rects = updates.map(({ x, y, w, h }) => ({
      left: Math.max(4, Math.min(x - w / 2, cw - w - 4)),
      top: Math.max(4, Math.min(y - h, ch - h - 4)),
      w,
      h,
    }))

    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i], b = rects[j]
        const overlapX = a.left < b.left + b.w && a.left + a.w > b.left
        const overlapY = a.top < b.top + b.h && a.top + a.h > b.top
        if (overlapX && overlapY) {
          if (a.top <= b.top) {
            a.top = Math.max(4, b.top - a.h - 4)
          } else {
            b.top = Math.max(4, a.top - b.h - 4)
          }
        }
      }
    }

    for (let i = 0; i < updates.length; i++) {
      const { el, x: spriteX } = updates[i]
      const { left, top, w } = rects[i]
      el.style.display = ''
      el.style.transform = `translate(${left}px, ${top}px)`
      el.style.opacity = '1'

      const arrow = el.querySelector('.bubble-arrow') as HTMLDivElement | null
      if (arrow) {
        const arrowX = Math.max(10, Math.min(spriteX - left, w - 10))
        arrow.style.left = `${arrowX}px`
        arrow.style.marginLeft = '-6px'
      }
    }
  }

  clear() {
    for (const el of this.elements.values()) el.remove()
    this.elements.clear()
  }

  destroy() {
    this.clear()
    this.container.remove()
  }

  private createBubbleEl(b: BubbleData): HTMLDivElement {
    const el = document.createElement('div')
    el.className = `bubble bubble-${b.type}`
    el.dataset.bubbleType = b.type
    el.dataset.agentId = b.agentId

    const interactive = b.type !== 'action'

    if (b.type === 'emoji') {
      // Pixel-art balloon: fixed 48×48 (32×32 source scaled 1.5× w/ nearest).
      Object.assign(el.style, {
        position: 'absolute',
        left: '0',
        top: '0',
        width: '48px',
        height: '48px',
        imageRendering: 'pixelated',
        backgroundSize: 'contain',
        backgroundRepeat: 'no-repeat',
        backgroundPosition: 'center',
        pointerEvents: 'auto',
        cursor: 'pointer',
        opacity: '0',
        transition: 'opacity 0.3s',
        willChange: 'transform',
        filter: 'drop-shadow(0 2px 2px rgba(0,0,0,0.25))',
      })
    } else if (b.type === 'action') {
      Object.assign(el.style, {
        position: 'absolute',
        left: '0',
        top: '0',
        maxWidth: '220px',
        padding: '3px 8px',
        borderRadius: '5px',
        fontSize: '14px',
        lineHeight: '1.4',
        fontFamily: '"Noto Sans SC", sans-serif',
        fontStyle: 'italic',
        color: 'rgba(255,255,255,0.65)',
        background: 'rgba(0,0,0,0.25)',
        whiteSpace: 'pre-wrap',
        overflowWrap: 'break-word',
        pointerEvents: 'none',
        opacity: '0',
        transition: 'opacity 0.3s',
        willChange: 'transform',
      })
    } else {
      Object.assign(el.style, {
        position: 'absolute',
        left: '0',
        top: '0',
        maxWidth: '300px',
        padding: '9px 14px',
        borderRadius: '10px',
        fontSize: '17px',
        lineHeight: '1.55',
        fontFamily: '"Noto Sans SC", sans-serif',
        whiteSpace: 'pre-wrap',
        overflowWrap: 'break-word',
        overflow: 'visible',
        pointerEvents: 'auto',
        cursor: 'pointer',
        opacity: '0',
        transition: 'opacity 0.3s',
        willChange: 'transform',
      })
    }

    if (interactive && this.onBubbleClick) {
      const cb = this.onBubbleClick
      el.addEventListener('click', (e) => {
        e.stopPropagation()
        const id = el.dataset.agentId
        if (id) cb(id)
      })
    }

    return el
  }

  private updateBubbleContent(el: HTMLDivElement, b: BubbleData) {
    if (b.type === 'emoji') {
      // Prefer pixel-art balloon PNG keyed by emotion; if no emotion
      // provided (older callers), fall back to the emoji glyph.
      if (b.emotion) {
        el.style.backgroundImage = `url('/data/balloons/${b.emotion}.png')`
        el.textContent = ''
      } else {
        el.style.backgroundImage = ''
        el.textContent = b.text
      }
      return
    }

    if (b.type === 'action') {
      el.textContent = b.text
      return
    }

    Object.assign(el.style, {
      background: '#faf3e0',
      border: '1.5px solid #e0d5c0',
      color: '#2c2c2c',
    })

    const nameHtml = `<span style="font-weight:600;font-size:13px;opacity:0.75">${b.displayName}</span><br/>`
    el.innerHTML = `${nameHtml}${b.text}`

    const arrow = el.querySelector('.bubble-arrow') as HTMLDivElement | null
        ?? document.createElement('div')
    arrow.className = 'bubble-arrow'
    Object.assign(arrow.style, {
      position: 'absolute',
      left: '50%',
      bottom: '-6px',
      marginLeft: '-6px',
      width: '0',
      height: '0',
      borderLeft: '6px solid transparent',
      borderRight: '6px solid transparent',
      borderTop: '6px solid #faf3e0',
    })
    el.appendChild(arrow)
  }
}

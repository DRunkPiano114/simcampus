import { Container } from 'pixi.js'

export interface BubbleData {
  agentId: string
  displayName: string
  text: string
  type: 'speech' | 'thought' | 'emoji' | 'action'
  target?: string
  /** Inline inner thought shown below speech content (mind-reading mode) */
  subtext?: string
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

  /** Set which bubbles to show. Call when tick changes. */
  setBubbles(bubbles: BubbleData[]) {
    // Remove stale
    const activeIds = new Set(bubbles.map(b => b.agentId))
    for (const [id, el] of this.elements) {
      if (!activeIds.has(id)) {
        el.remove()
        this.elements.delete(id)
      }
    }

    // Create or update (recreate if type changed)
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

  /**
   * Update positions. Called from PixiJS Ticker (same rAF frame as render).
   * Projects character world positions to screen coordinates.
   * Clamps bubbles to stay within the container viewport.
   */
  updatePositions(
    sprites: Map<string, Container>,
    worldContainer: Container,
  ) {
    const cw = this.container.offsetWidth
    const ch = this.container.offsetHeight

    // Batch reads (dimensions), then batch writes (transforms)
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

    // Compute clamped positions
    const rects = updates.map(({ x, y, w, h }) => ({
      left: Math.max(4, Math.min(x - w / 2, cw - w - 4)),
      top: Math.max(4, Math.min(y - h, ch - h - 4)),
      w,
      h,
    }))

    // Push overlapping bubbles apart vertically (single pass, O(n²) but n≤8)
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i], b = rects[j]
        const overlapX = a.left < b.left + b.w && a.left + a.w > b.left
        const overlapY = a.top < b.top + b.h && a.top + a.h > b.top
        if (overlapX && overlapY) {
          // Push the higher one (smaller top) further up
          if (a.top <= b.top) {
            a.top = Math.max(4, b.top - a.h - 4)
          } else {
            b.top = Math.max(4, a.top - b.h - 4)
          }
        }
      }
    }

    // Batch writes
    for (let i = 0; i < updates.length; i++) {
      const { el, x: spriteX } = updates[i]
      const { left, top, w } = rects[i]
      el.style.display = ''
      el.style.transform = `translate(${left}px, ${top}px)`
      el.style.opacity = '1'

      // Dynamic arrow: point at the character's actual screen X
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
      Object.assign(el.style, {
        position: 'absolute',
        left: '0',
        top: '0',
        fontSize: '20px',
        lineHeight: '1',
        textAlign: 'center',
        pointerEvents: 'auto',
        cursor: 'pointer',
        opacity: '0',
        transition: 'opacity 0.3s',
        willChange: 'transform',
        filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.3))',
      })
    } else if (b.type === 'action') {
      Object.assign(el.style, {
        position: 'absolute',
        left: '0',
        top: '0',
        maxWidth: '180px',
        padding: '2px 6px',
        borderRadius: '4px',
        fontSize: '11px',
        lineHeight: '1.3',
        fontFamily: '"Noto Sans SC", sans-serif',
        fontStyle: 'italic',
        color: 'rgba(255,255,255,0.6)',
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
        maxWidth: '200px',
        padding: '6px 10px',
        borderRadius: '8px',
        fontSize: '13px',
        lineHeight: '1.4',
        fontFamily: b.type === 'thought'
          ? '"LXGW WenKai", serif'
          : '"Noto Sans SC", sans-serif',
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

    // Forward clicks to focusAgent (same as clicking the PixiJS sprite)
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
      el.textContent = b.text
      if (b.subtext) el.title = b.subtext
      return
    }

    if (b.type === 'action') {
      el.textContent = b.text
      return
    }

    const isThought = b.type === 'thought'

    Object.assign(el.style, {
      background: isThought ? 'rgba(255,235,240,0.92)' : '#faf3e0',
      border: isThought ? '1.5px dashed rgba(233,69,96,0.5)' : '1.5px solid #e0d5c0',
      fontStyle: isThought ? 'italic' : 'normal',
      color: isThought ? '#c0475a' : '#2c2c2c',
    })

    const nameHtml = `<span style="font-weight:600;font-size:11px;opacity:0.7">${b.displayName}</span><br/>`

    let html = `${nameHtml}${b.text}`

    // Inline inner thought below speech content (mind-reading mode)
    if (b.subtext && b.type === 'speech') {
      html += `<div style="margin-top:3px;padding-top:3px;border-top:1px dashed rgba(233,69,96,0.3);font-style:italic;font-size:11px;color:#c0475a;font-family:'LXGW WenKai',serif">${b.subtext}</div>`
    }

    el.innerHTML = html

    // Pointer triangle pointing down toward the character
    const arrow = el.querySelector('.bubble-arrow') as HTMLDivElement | null
        ?? document.createElement('div')
    arrow.className = 'bubble-arrow'
    const arrowColor = isThought ? 'rgba(255,235,240,0.92)' : '#faf3e0'
    Object.assign(arrow.style, {
      position: 'absolute',
      left: '50%',
      bottom: '-6px',
      marginLeft: '-6px',
      width: '0',
      height: '0',
      borderLeft: '6px solid transparent',
      borderRight: '6px solid transparent',
      borderTop: `6px solid ${arrowColor}`,
    })
    el.appendChild(arrow)
  }
}

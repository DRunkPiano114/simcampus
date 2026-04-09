import { Container } from 'pixi.js'

const LERP_SPEED = 0.08
const MIN_ZOOM = 0.3
const MAX_ZOOM = 3
const ZOOM_STEP = 0.1

/**
 * Camera controller. State lives on the PixiJS Container transform,
 * NOT in Zustand (avoids 60fps store writes).
 */
export class Camera {
  private targetX = 0
  private targetY = 0
  private targetZoom = 1
  private currentZoom = 1
  private isDragging = false
  private dragStart = { x: 0, y: 0 }
  private pivotStart = { x: 0, y: 0 }

  constructor(
    private worldContainer: Container,
    private canvasWidth: number,
    private canvasHeight: number,
  ) {}

  /** Snap camera to position (no lerp). */
  jumpTo(x: number, y: number, zoom = 1) {
    this.targetX = x
    this.targetY = y
    this.targetZoom = zoom
    this.currentZoom = zoom
    this.apply(x, y, zoom)
  }

  /** Smoothly pan to target. */
  panTo(x: number, y: number) {
    this.targetX = x
    this.targetY = y
  }

  /** Set zoom level for smooth transition. */
  zoomTo(zoom: number) {
    this.targetZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom))
  }

  /** Snap camera to fit room within viewport, accounting for UI overlay insets. */
  fitToRoom(
    roomW: number,
    roomH: number,
    inset: { top: number; bottom: number; left: number; right: number },
  ) {
    const viewW = this.canvasWidth - inset.left - inset.right
    const viewH = this.canvasHeight - inset.top - inset.bottom
    const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.min(viewW / roomW, viewH / roomH)))
    this.targetZoom = zoom
    this.currentZoom = zoom
    // Center on room center, offset by inset asymmetry
    const offsetX = (inset.left - inset.right) / 2 / zoom
    const offsetY = (inset.top - inset.bottom) / 2 / zoom
    this.targetX = roomW / 2 - offsetX
    this.targetY = roomH / 2 - offsetY
    this.apply(this.targetX, this.targetY, zoom)
  }

  /** Call every frame (from PixiJS Ticker). */
  update() {
    if (this.isDragging) return

    const px = this.worldContainer.pivot.x
    const py = this.worldContainer.pivot.y

    const nx = px + (this.targetX - px) * LERP_SPEED
    const ny = py + (this.targetY - py) * LERP_SPEED
    this.currentZoom += (this.targetZoom - this.currentZoom) * LERP_SPEED

    this.apply(nx, ny, this.currentZoom)
  }

  private apply(x: number, y: number, zoom: number) {
    this.worldContainer.pivot.set(x, y)
    this.worldContainer.position.set(this.canvasWidth / 2, this.canvasHeight / 2)
    this.worldContainer.scale.set(zoom)
  }

  // --- mouse handlers (for explore mode) ---

  onPointerDown(globalX: number, globalY: number) {
    this.isDragging = true
    this.dragStart = { x: globalX, y: globalY }
    this.pivotStart = {
      x: this.worldContainer.pivot.x,
      y: this.worldContainer.pivot.y,
    }
  }

  onPointerMove(globalX: number, globalY: number) {
    if (!this.isDragging) return
    const dx = (globalX - this.dragStart.x) / this.currentZoom
    const dy = (globalY - this.dragStart.y) / this.currentZoom
    const nx = this.pivotStart.x - dx
    const ny = this.pivotStart.y - dy
    this.targetX = nx
    this.targetY = ny
    this.apply(nx, ny, this.currentZoom)
  }

  onPointerUp() {
    this.isDragging = false
  }

  onWheel(delta: number) {
    const step = delta > 0 ? -ZOOM_STEP : ZOOM_STEP
    this.zoomTo(this.currentZoom + step)
  }

  /** Resize handler. */
  resize(w: number, h: number) {
    this.canvasWidth = w
    this.canvasHeight = h
  }
}

import { Graphics, Text, TextStyle, Container, Rectangle, Sprite, Texture, Assets } from 'pixi.js'

const TILE = 32

/** Fallback agent colors — seeded from visual_bible.json. Overridden at runtime
 * once /data/agent_colors.json loads via primeAgentColors(). Keep the fallback
 * here so sprites created before the fetch resolves still get a reasonable color.
 */
const AGENT_COLORS: Record<string, number> = {
  lin_zhaoyu: 0x4a7bc4,
  lu_siyuan: 0x5baa5b,
  shen_yifan: 0xc4524a,
  cheng_yutong: 0xe8a838,
  fang_yuchen: 0xb06ab3,
  tang_shihan: 0x4ac4a8,
  su_nianyao: 0xd4748b,
  jiang_haotian: 0xe87b42,
  he_jiajun: 0x7b8fa8,
  he_min: 0x8b6e4e,
}

/** Sprite states affecting animation. */
export type SpriteState = 'idle' | 'talking' | 'action'

export function getAgentColor(agentId: string): number {
  return AGENT_COLORS[agentId] ?? 0x888888
}

/** Replace the in-memory palette from the authoritative JSON export. */
export function primeAgentColors(
  map: Record<string, { main_color: string }>,
): void {
  for (const [id, v] of Object.entries(map)) {
    const hex = v.main_color.replace('#', '')
    const n = parseInt(hex, 16)
    if (!Number.isNaN(n)) AGENT_COLORS[id] = n
  }
}

/** Preload all map sprite textures so Sprite.from() hits cache and renders
 * pixel-perfect (nearest scaling) on first frame.
 */
export async function preloadMapSprites(agentIds: string[]): Promise<void> {
  await Promise.all(
    agentIds.map(async aid => {
      try {
        const tex = await Assets.load(`/data/map_sprites/${aid}.png`)
        if (tex?.source) tex.source.scaleMode = 'nearest'
      } catch {
        // Missing sprite is non-fatal — sprite will render empty and the
        // name label still identifies the character.
      }
    }),
  )
}

/**
 * Create a character display object (Container with pixel sprite + label).
 * Returns a PixiJS Container that can be added to a room layer.
 *
 * Layout (container origin at tile center):
 *   sprite (32x64 pixel art) z=0, anchor (0.5, 0.5) → centered on tile
 *   label (Text)             z=1, below sprite
 */
export function createCharacterSprite(
  agentId: string,
  displayName: string,
): Container {
  const container = new Container()
  container.label = agentId

  const color = getAgentColor(agentId)

  // Pixel-art character sprite (32×64 native; rendered at 1× pixel scale).
  // Pixi v8's Texture.from(url) returns EMPTY unless the asset is preloaded;
  // async-load here and swap the texture in when ready (Assets dedupes).
  const sprite = new Sprite(Texture.EMPTY)
  sprite.anchor.set(0.5, 0.5)
  sprite.label = '__body'
  container.addChild(sprite)

  Assets.load(`/data/map_sprites/${agentId}.png`)
    .then((tex: Texture) => {
      if (tex?.source) tex.source.scaleMode = 'nearest'
      sprite.texture = tex
    })
    .catch(() => {
      // Missing sprite fallback — draw a colored circle so the character
      // still has a visible body anchored at the tile.
      sprite.visible = false
      const fallback = new Graphics()
      fallback.circle(0, 0, TILE * 0.4).fill(color)
      fallback.circle(0, 0, TILE * 0.4).stroke({ color: 0xffffff, width: 2, alpha: 0.6 })
      fallback.label = '__body'
      container.addChild(fallback)
    })

  // Name label — placed below the sprite so a 3-char name doesn't clip the body.
  const label = new Text({
    text: displayName,
    style: new TextStyle({
      fontFamily: '"Noto Sans SC", sans-serif',
      fontSize: 11,
      fill: 0xffffff,
      fontWeight: 'bold',
      stroke: { color: 0x000000, width: 3, alpha: 0.7 },
      dropShadow: {
        color: 0x000000,
        blur: 2,
        distance: 1,
        alpha: 0.6,
      },
    }),
  })
  label.anchor.set(0.5, 0)
  label.y = 34
  container.addChild(label)

  // Hit area covers the full sprite (32×64 centered) plus the label below.
  container.hitArea = new Rectangle(-18, -34, 36, 82)

  return container
}

/**
 * Update sprite visual state (dimming, slight float while talking).
 */
export function updateSpriteState(
  container: Container,
  state: SpriteState,
  dimmed: boolean,
) {
  container.alpha = dimmed ? 0.4 : 1
  const body = container.getChildByLabel('__body') as Sprite | null
  if (body) body.y = state === 'talking' ? -3 : 0
}

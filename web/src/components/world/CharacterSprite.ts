import { Graphics, Text, TextStyle, Container } from 'pixi.js'

const TILE = 32
const SPRITE_R = TILE * 0.4

/** Character visual colors — each agent gets a consistent color. */
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

/**
 * Create a character display object (Container with circle + label).
 * Returns a PixiJS Container that can be added to a room layer.
 */
export function createCharacterSprite(
  agentId: string,
  displayName: string,
): Container {
  const container = new Container()
  container.label = agentId

  const color = getAgentColor(agentId)

  // Body circle
  const body = new Graphics()
  body.circle(0, 0, SPRITE_R).fill(color)
  body.circle(0, 0, SPRITE_R).stroke({ color: 0xffffff, width: 2, alpha: 0.6 })
  container.addChild(body)

  // Head (smaller circle on top)
  const head = new Graphics()
  head.circle(0, -SPRITE_R * 1.1, SPRITE_R * 0.55).fill(0xf5dcc0) // skin tone
  head.circle(0, -SPRITE_R * 1.1, SPRITE_R * 0.55).stroke({ color: color, width: 2 })
  container.addChild(head)

  // Name label
  const label = new Text({
    text: displayName.slice(0, 2), // first 2 chars (surname)
    style: new TextStyle({
      fontFamily: '"Noto Sans SC", sans-serif',
      fontSize: 11,
      fill: 0xffffff,
      fontWeight: 'bold',
      dropShadow: {
        color: 0x000000,
        blur: 2,
        distance: 1,
        alpha: 0.5,
      },
    }),
  })
  label.anchor.set(0.5, 0)
  label.y = SPRITE_R * 0.5
  container.addChild(label)

  return container
}

/**
 * Update sprite visual state (talking pulse, dimming, etc.)
 */
export function updateSpriteState(
  container: Container,
  state: SpriteState,
  dimmed: boolean,
) {
  container.alpha = dimmed ? 0.4 : 1
  // Talking: slight scale pulse
  const scale = state === 'talking' ? 1.1 : 1
  container.scale.set(scale)
}

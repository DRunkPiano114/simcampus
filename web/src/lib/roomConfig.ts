import type { RoomId, RoomLayout, RoomZone } from './types'

export const TILE = 32

/** Room dimensions and zone definitions for all 7 locations. */
export const ROOMS: Record<RoomId, RoomLayout> = {
  '教室': {
    id: '教室', label: 'Classroom', cols: 24, rows: 18,
    zones: zones5x4Classroom(),
  },
  '走廊': {
    id: '走廊', label: 'Hallway', cols: 28, rows: 10,
    zones: [
      { id: 'left', x: 6, y: 4, capacity: 4 },
      { id: 'center', x: 14, y: 4, capacity: 4 },
      { id: 'right', x: 22, y: 4, capacity: 4 },
    ],
  },
  '食堂': {
    id: '食堂', label: 'Cafeteria', cols: 28, rows: 20,
    zones: [
      { id: 'table_1', x: 4, y: 5, capacity: 4 },
      { id: 'table_2', x: 14, y: 5, capacity: 4 },
      { id: 'table_3', x: 24, y: 5, capacity: 4 },
      { id: 'table_4', x: 4, y: 13, capacity: 4 },
      { id: 'table_5', x: 14, y: 13, capacity: 4 },
      { id: 'table_6', x: 24, y: 13, capacity: 4 },
    ],
  },
  '宿舍': {
    id: '宿舍', label: 'Dorm', cols: 24, rows: 16,
    zones: [
      { id: 'bed_1', x: 3, y: 4, capacity: 2 },
      { id: 'bed_2', x: 10, y: 4, capacity: 2 },
      { id: 'bed_3', x: 17, y: 4, capacity: 2 },
      { id: 'desk_area', x: 10, y: 10, capacity: 4 },
    ],
  },
  '操场': {
    id: '操场', label: 'Playground', cols: 30, rows: 20,
    zones: [
      { id: 'court', x: 15, y: 8, capacity: 6 },
      { id: 'bench_left', x: 3, y: 14, capacity: 3 },
      { id: 'bench_right', x: 25, y: 14, capacity: 3 },
      { id: 'track', x: 15, y: 17, capacity: 4 },
    ],
  },
  '图书馆': {
    id: '图书馆', label: 'Library', cols: 24, rows: 18,
    zones: [
      { id: 'table_1', x: 5, y: 6, capacity: 3 },
      { id: 'table_2', x: 13, y: 6, capacity: 3 },
      { id: 'table_3', x: 5, y: 12, capacity: 3 },
      { id: 'table_4', x: 13, y: 12, capacity: 3 },
      { id: 'shelves', x: 20, y: 9, capacity: 2 },
    ],
  },
  '小卖部': {
    id: '小卖部', label: 'Convenience Store', cols: 16, rows: 14,
    zones: [
      { id: 'counter', x: 8, y: 3, capacity: 2 },
      { id: 'aisle_1', x: 4, y: 8, capacity: 3 },
      { id: 'aisle_2', x: 11, y: 8, capacity: 3 },
    ],
  },
}

function zones5x4Classroom(): RoomZone[] {
  // 5 columns × 4 rows matching SEAT_LAYOUT
  const zones: RoomZone[] = []
  const cx = [3.5, 7.5, 11.5, 15.5, 19.5]
  const ry = [6, 9, 12, 15]
  let seatNum = 1
  for (const r of ry) {
    for (const c of cx) {
      zones.push({ id: `seat_${seatNum}`, x: c, y: r + 0.5, capacity: 1 })
      seatNum++
    }
  }
  // Teacher zone
  zones.push({ id: 'teacher', x: 12, y: 3.5, capacity: 1 })
  return zones
}

/**
 * Derive pixel positions for participants within a room.
 * Groups are assigned to zones; characters spread within their zone.
 */
export function derivePositions(
  room: RoomId,
  participants: string[],
  groupIndex: number,
  agentMeta?: Record<string, { seat_number: number | null }>,
): Record<string, { x: number; y: number }> {
  const layout = ROOMS[room]
  if (!layout) return fallbackPositions(participants)

  // Classroom: use seat positions from agent metadata
  if (room === '教室' && agentMeta) {
    const positions: Record<string, { x: number; y: number }> = {}
    for (const id of participants) {
      const seat = agentMeta[id]?.seat_number
      const zone = seat ? layout.zones.find(z => z.id === `seat_${seat}`) : null
      if (zone) {
        positions[id] = { x: zone.x * TILE, y: zone.y * TILE }
      } else {
        // Teacher or unknown: teacher zone
        const tz = layout.zones.find(z => z.id === 'teacher')!
        positions[id] = { x: tz.x * TILE, y: tz.y * TILE }
      }
    }
    return positions
  }

  // Other rooms: assign group to a zone, spread participants within it
  const availableZones = layout.zones.filter(z => z.id !== 'teacher')
  const zone = availableZones[groupIndex % availableZones.length]
  const positions: Record<string, { x: number; y: number }> = {}

  const pad = TILE * 1.5
  const minX = pad
  const maxX = (layout.cols - 1) * TILE - pad
  const minY = pad
  const maxY = (layout.rows - 1) * TILE - pad

  participants.forEach((id, i) => {
    const angle = (i / participants.length) * Math.PI * 2
    const spread = Math.min(participants.length, 4) * TILE * 1.0
    positions[id] = {
      x: Math.max(minX, Math.min(maxX, zone.x * TILE + Math.cos(angle) * spread)),
      y: Math.max(minY, Math.min(maxY, zone.y * TILE + Math.sin(angle) * spread * 0.6)),
    }
  })

  return positions
}

function fallbackPositions(participants: string[]): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {}
  participants.forEach((id, i) => {
    positions[id] = { x: (3 + i * 3) * TILE, y: 8 * TILE }
  })
  return positions
}

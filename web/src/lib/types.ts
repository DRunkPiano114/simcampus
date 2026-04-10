// --- Emotion ---

export type Emotion =
  | 'happy' | 'sad' | 'anxious' | 'angry' | 'excited'
  | 'calm' | 'embarrassed' | 'bored' | 'neutral' | 'jealous' | 'proud'

// --- Scene file (top-level) ---

export interface SceneInfo {
  scene_index: number
  time: string
  name: string
  location: string
  description: string
  day: number
}

export interface Speech {
  agent: string
  target: string | null
  content: string
}

export interface PublicAction {
  agent: string
  type: string // ActionType value
  content: string | null
}

export interface PublicLayer {
  speech: Speech | null
  actions: PublicAction[]
  environmental_event: string | null
  exits: string[]
}

export interface MindState {
  inner_thought: string
  observation: string
  emotion: Emotion
  action_type: string
  action_content: string | null
  action_target: string | null
  urgency: number
  is_disruptive: boolean
}

export interface Tick {
  tick: number
  public: PublicLayer
  minds: Record<string, MindState>
}

// --- Narrative extraction ---

export interface NarrativeExtraction {
  key_moments: string[]
  fulfilled_intentions: string[]
  events_discussed: string[]
  new_events: Array<{
    text: string
    category: string
    witnesses: string[]
    spread_probability: number
  }>
}

// --- Reflections ---

export interface RelationshipChange {
  to_agent: string
  favorability: number
  trust: number
  understanding: number
}

export interface AgentReflection {
  emotion: Emotion
  relationship_changes: RelationshipChange[]
  memories: Array<{
    text: string
    emotion: string
    importance: number
    people: string[]
    location: string
    topics: string[]
  }>
  new_concerns: Array<{
    text: string
    source_event: string
    emotion: string
    intensity: number
    related_people: string[]
    positive: boolean
  }>
}

// --- Groups ---

export interface SoloReflection {
  inner_thought: string
  emotion: Emotion
  activity: string
}

export interface SceneGroup {
  group_index: number
  participants: string[]
  ticks: Tick[]
  narrative: NarrativeExtraction
  reflections: Record<string, AgentReflection>
  is_solo?: false
}

export interface SoloGroup {
  group_index: number
  participants: string[]
  is_solo: true
  solo_reflection: SoloReflection
}

export type GroupData = SceneGroup | SoloGroup

export interface SceneFile {
  scene: SceneInfo
  participant_names: Record<string, string>
  groups: GroupData[]
}

// --- Scenes index ---

export interface SceneIndexEntry {
  scene_index: number
  time: string
  name: string
  location: string
  file: string
  groups: Array<{
    group_index: number
    participants: string[]
    is_solo: boolean
  }>
}

// --- Agent ---

export interface Academics {
  overall_rank: string
  strengths: string[]
  weaknesses: string[]
  study_attitude: string
  target: string
  homework_habit: string
}

export interface FamilyBackground {
  pressure_level: string
  expectation: string
  situation: string
}

export interface ActiveConcern {
  text: string
  source_event: string
  emotion: string
  intensity: number
  related_people: string[]
  positive: boolean
  source_day: number
  source_scene: string
}

export interface AgentState {
  emotion: Emotion
  energy: number
  academic_pressure: number
  location: string
  daily_plan: {
    intentions: Array<{ goal: string; priority: number }>
    mood_forecast: string
  }
  day: number
  active_concerns: ActiveConcern[]
}

export interface Relationship {
  target_name: string
  target_id: string
  favorability: number
  trust: number
  understanding: number
  label: string
  recent_interactions: string[]
}

export interface Agent {
  agent_id: string
  name: string
  gender: string
  role: string
  seat_number: number | null
  dorm_id: string | null
  position: string | null
  personality: string[]
  speaking_style: string
  academics: Academics
  family_background: FamilyBackground
  long_term_goals: string[]
  inner_conflicts: string[]
  backstory: string
  state: AgentState
  relationships: Record<string, Relationship>
  self_narrative: string
  key_memories: Array<{
    date: string
    day: number
    people: string[]
    location: string
    emotion: string
    importance: number
    topics: string[]
    text: string
  }>
}

// --- Meta ---

export interface AgentMeta {
  name: string
  role: string
  gender: string | null
  seat_number: number | null
  position: string | null
  dorm_id: string | null
}

export interface ScheduleEntry {
  time: string
  name: string
  location: string
  density: string
  max_rounds: number
  trigger_probability: number
  description: string
  opening_events?: string[]
  is_free_period?: boolean
}

export interface Meta {
  days: string[]
  agents: Record<string, AgentMeta>
  schedule: ScheduleEntry[]
  current_date: string
  next_exam_in_days: number
}

// --- Events ---

export interface GameEvent {
  id: string
  source_scene: string
  source_day: number
  text: string
  category: string
  witnesses: string[]
  known_by: string[]
  spread_probability: number
  active: boolean
}

// --- Trajectory ---

export interface AgentSlot {
  time: string
  scene_name: string
  location: string
  activity: string
  emotion: string
}

export interface DayTrajectory {
  day: number
  agents: Record<string, AgentSlot[]>
}

// --- Pixel world types ---

export type RoomId = '教室' | '走廊' | '食堂' | '宿舍' | '操场' | '图书馆' | '小卖部'

export interface RoomZone {
  id: string
  x: number
  y: number
  capacity: number
}

export interface RoomLayout {
  id: RoomId
  label: string
  cols: number
  rows: number
  zones: RoomZone[]
}

export interface CharacterPosition {
  x: number
  y: number
  room: RoomId
}

export type ViewMode = 'explore' | 'broadcast'

export type PlaybackSpeed = 1 | 2 | 4

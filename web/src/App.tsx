import { Routes, Route, Navigate } from 'react-router-dom'
import { PixiCanvas } from './components/world/PixiCanvas'
import { DailyReport, DailyReportHome } from './components/daily/DailyReport'
import { CharacterGallery, CharacterArchivePage } from './components/gallery/CharacterGallery'
import { GodModeChat } from './components/ui/GodModeChat'
import { RolePlayChat } from './components/ui/RolePlayChat'

// Legacy routes — kept available during transition
import { PageShell } from './components/layout/PageShell'
import { ForceGraph } from './components/relationships/ForceGraph'
import { EmotionTimeline } from './components/timeline/EmotionTimeline'

export default function App() {
  return (
    <>
      <Routes>
        {/* Landing = 班级日报. Redirects to /day/<latest>. */}
        <Route path="/" element={<DailyReportHome />} />
        <Route path="/day/:dayId" element={<DailyReport />} />

        {/* Pixel-art world viewer — scene deep-dive, reached from a daily link. */}
        <Route path="/day/:dayId/scene/:sceneFile" element={<PixiCanvas />} />

        {/* Character archive gallery */}
        <Route path="/characters" element={<CharacterGallery />} />
        <Route path="/characters/day/:dayId" element={<CharacterGallery />} />
        <Route path="/characters/:agentId" element={<CharacterArchivePage />} />

        {/* Phase 2 analytical views (kept as-is) */}
        <Route path="/relationships" element={<PageShell><ForceGraph /></PageShell>} />
        <Route path="/timeline" element={<PageShell><EmotionTimeline /></PageShell>} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <GodModeChat />
      <RolePlayChat />
      <a
        href="https://github.com/DRunkPiano114/simcampus"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="View source on GitHub"
        className="fixed bottom-4 right-4 z-40 p-3.5 rounded-full bg-paper border border-ink/30 text-ink hover:bg-amber/25 shadow-md transition-colors"
      >
        <svg viewBox="0 0 24 24" width="36" height="36" fill="currentColor" aria-hidden="true">
          <path d="M12 .5C5.73.5.67 5.56.67 11.84c0 5.02 3.26 9.28 7.78 10.79.57.1.78-.25.78-.55 0-.27-.01-1.17-.02-2.12-3.17.69-3.84-1.34-3.84-1.34-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.69.08-.69 1.15.08 1.76 1.18 1.76 1.18 1.02 1.75 2.68 1.24 3.34.95.1-.74.4-1.25.72-1.54-2.53-.29-5.19-1.27-5.19-5.64 0-1.25.45-2.27 1.18-3.07-.12-.29-.51-1.45.11-3.03 0 0 .96-.31 3.15 1.17a10.94 10.94 0 0 1 5.74 0c2.19-1.48 3.15-1.17 3.15-1.17.62 1.58.23 2.74.11 3.03.73.8 1.18 1.82 1.18 3.07 0 4.38-2.67 5.35-5.21 5.63.41.35.77 1.05.77 2.12 0 1.53-.01 2.76-.01 3.14 0 .3.21.66.79.55 4.51-1.51 7.77-5.77 7.77-10.79C23.33 5.56 18.27.5 12 .5z"/>
        </svg>
      </a>
    </>
  )
}

import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import './index.css'
import { About } from './pages/About'
import { Ask } from './pages/Ask'
import { NotFound } from './pages/NotFound'
import { Overview } from './pages/Overview'
import { TrackRecord } from './pages/TrackRecord'

// The ticker page is the only one with a chart, so the charting library loads on demand.
const TickerDetail = lazy(() =>
  import('./pages/TickerDetail').then((module) => ({ default: module.TickerDetail })),
)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route
            path="tickers/:ticker"
            element={
              <Suspense fallback={<div className="state-box muted">Loading…</div>}>
                <TickerDetail />
              </Suspense>
            }
          />
          <Route path="track-record" element={<TrackRecord />} />
          <Route path="ask" element={<Ask />} />
          <Route path="about" element={<About />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)

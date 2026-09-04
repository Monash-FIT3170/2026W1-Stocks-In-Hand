"use client"

import { useEffect, useState } from "react"
import { DeepDiveTimeline } from "../../../components/ticker/DeepDiveTimeline"
import { useTickerBrief } from "../../../components/ticker/TickerBriefShell"
import { fetchTickerDeepDive } from "../../../lib/api"
import pageStyles from "../../../page.module.css"
import styles from "../../../components/research/ResearchSurface.module.css"

// Ticker brief deep-dive tab for "/ticker/[symbol]/deep-dive".
// Timeline entries come from DB-backed ticker artifacts.
export default function TickerDeepDiveRoute() {
  const { isLoading: isBriefLoading, symbol } = useTickerBrief()
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState({
    error: "",
    isLoading: true,
    timeline: [],
  })

  useEffect(() => {
    // The brief endpoint initializes deployed tickers on a fresh database.
    // Waiting for it avoids racing the timeline request against that setup.
    if (isBriefLoading) return

    let cancelled = false

    async function loadDeepDive() {
      try {
        const timeline = await fetchTickerDeepDive(symbol)
        if (!cancelled) {
          setState({ error: "", isLoading: false, timeline })
        }
      } catch (error) {
        if (!cancelled) {
          setState({
            error: error instanceof Error
              ? error.message
              : "The deep-dive timeline is unavailable right now.",
            isLoading: false,
            timeline: [],
          })
        }
      }
    }

    loadDeepDive()
    return () => {
      cancelled = true
    }
  }, [attempt, isBriefLoading, symbol])

  if (state.isLoading) {
    return (
      <div className={pageStyles.contentSkeleton} aria-live="polite">Loading {symbol} deep dive…</div>
    )
  }

  if (state.error) {
    return (
      <div className={styles.statePanel} role="alert">
        <h2>Deep dive could not be loaded</h2>
        <p>{state.error}</p>
        <button className={styles.secondaryButton} onClick={() => setAttempt((value) => value + 1)} type="button">Try again</button>
      </div>
    )
  }

  const { timeline } = state

  return (
    <div className={styles.briefContent}>
      <header className={styles.newsHeader}><h2>Company timeline</h2><p>{timeline.length} source-led events</p></header>
      {timeline.length > 0 ? <DeepDiveTimeline timeline={timeline} /> : (
      <div className={styles.statePanel}>
        <h2>No deep-dive timeline yet</h2>
        <p>No announcements have been stored for {symbol} yet. Run the data pipeline to populate this timeline.</p>
      </div>
      )}
    </div>
  )
}

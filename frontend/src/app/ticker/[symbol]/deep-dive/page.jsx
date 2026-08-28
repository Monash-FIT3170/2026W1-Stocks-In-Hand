"use client"

import { useEffect, useState } from "react"
import { DeepDiveTimeline } from "../../../components/ticker/DeepDiveTimeline"
import { useTickerBrief } from "../../../components/ticker/TickerBriefShell"
import { fetchTickerDeepDive } from "../../../lib/api"
import styles from "../../../page.module.css"

// Ticker brief deep-dive tab for "/ticker/[symbol]/deep-dive".
// Timeline entries come from DB-backed ticker artifacts.
export default function TickerDeepDiveRoute() {
  const { symbol } = useTickerBrief()
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState({
    error: "",
    isLoading: true,
    timeline: [],
  })

  useEffect(() => {
    let cancelled = false

    async function loadDeepDive() {
      try {
        const timeline = await fetchTickerDeepDive(symbol)
        if (!cancelled) {
          setState({ error: "", isLoading: false, timeline })
        }
      } catch {
        if (!cancelled) {
          setState({ error: "The deep-dive timeline is unavailable right now. Check your connection and try again.", isLoading: false, timeline: [] })
        }
      }
    }

    loadDeepDive()
    return () => {
      cancelled = true
    }
  }, [attempt, symbol])

  if (state.isLoading) {
    return (
      <div className={styles.contentSkeleton} aria-live="polite">Loading {symbol} deep dive…</div>
    )
  }

  if (state.error) {
    return (
      <div className={styles.emptyCard} role="alert">
        <h2>Deep dive could not be loaded</h2>
        <p>{state.error}</p>
        <button className={styles.secondaryButton} onClick={() => setAttempt((value) => value + 1)} type="button">Try again</button>
      </div>
    )
  }

  const { timeline } = state

  return (
    timeline.length > 0 ? <DeepDiveTimeline timeline={timeline} /> : (
      <div className={styles.emptyCard}>
        <h2>No deep-dive timeline yet</h2>
        <p>The analysis pipeline has not stored enough source material for {symbol}.</p>
      </div>
    )
  )
}

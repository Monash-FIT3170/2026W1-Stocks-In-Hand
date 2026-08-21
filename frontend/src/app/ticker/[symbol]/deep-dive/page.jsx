"use client"

import { useEffect, useState } from "react"
import { AppFrame } from "../../../components/layout/AppFrame"
import { BriefAside } from "../../../components/ticker/BriefAside"
import { BriefTabs } from "../../../components/ticker/BriefTabs"
import { DeepDiveTimeline } from "../../../components/ticker/DeepDiveTimeline"
import { TickerHeader } from "../../../components/ticker/TickerHeader"
import { fetchTickerBriefAside, fetchTickerDeepDive, fetchTickerOverview } from "../../../lib/api"
import styles from "../../../page.module.css"

// Ticker brief deep-dive tab for "/ticker/[symbol]/deep-dive".
// Timeline entries come from DB-backed ticker artifacts.
export default function TickerDeepDiveRoute({ params }) {
  const symbol = params.symbol.toUpperCase()
  const [state, setState] = useState({
    aside: null,
    error: false,
    isLoading: true,
    overview: null,
    timeline: [],
  })

  useEffect(() => {
    let cancelled = false

    async function loadDeepDive() {
      try {
        const [timeline, overview, aside] = await Promise.all([
          fetchTickerDeepDive(symbol),
          fetchTickerOverview(symbol),
          fetchTickerBriefAside(symbol),
        ])
        if (!cancelled) {
          setState({ aside, error: false, isLoading: false, overview, timeline })
        }
      } catch {
        if (!cancelled) {
          setState({ aside: null, error: true, isLoading: false, overview: null, timeline: [] })
        }
      }
    }

    loadDeepDive()
    return () => {
      cancelled = true
    }
  }, [symbol])

  if (state.isLoading) {
    return (
      <AppFrame active="home">
        <section className={styles.contentPage}>
          <div className={styles.emptyCard}><h3>Loading {symbol} deep dive...</h3></div>
        </section>
      </AppFrame>
    )
  }

  if (state.error) {
    return (
      <AppFrame active="home">
        <section className={styles.contentPage}>
          <div className={styles.emptyCard}>
            <h3>{symbol} not found</h3>
            <p>This ticker is not in the database yet. It will appear once the data pipeline has run.</p>
          </div>
        </section>
      </AppFrame>
    )
  }

  const { timeline, overview, aside } = state

  return (
    <AppFrame active="home">
      <section className={styles.contentPage}>
        <div className={styles.briefShell}>
          <div className={styles.briefMain}>
            <TickerHeader data={overview} />
            <BriefTabs active="deep" symbol={symbol} />
            <DeepDiveTimeline timeline={timeline} />
          </div>
          <BriefAside data={aside} />
        </div>
      </section>
    </AppFrame>
  )
}

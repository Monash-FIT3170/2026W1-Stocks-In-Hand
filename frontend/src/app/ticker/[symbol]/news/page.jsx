"use client"

import { useEffect, useState } from "react"
import { AnnouncementCard } from "../../../components/announcements/AnnouncementCard"
import { useTickerBrief } from "../../../components/ticker/TickerBriefShell"
import { fetchTickerNews } from "../../../lib/api"
import pageStyles from "../../../page.module.css"
import styles from "../../../components/research/ResearchSurface.module.css"

// Ticker brief news tab for "/ticker/[symbol]/news".
// This reuses AnnouncementCard and renders only DB-backed ticker announcements.
export default function TickerNewsRoute() {
  const { symbol } = useTickerBrief()
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState({
    error: "",
    isLoading: true,
    news: [],
  })

  useEffect(() => {
    let cancelled = false

    async function loadNews() {
      try {
        const news = await fetchTickerNews(symbol)
        if (!cancelled) {
          setState({ error: "", isLoading: false, news })
        }
      } catch {
        if (!cancelled) {
          setState({ error: "News is unavailable right now. Check your connection and try again.", isLoading: false, news: [] })
        }
      }
    }

    loadNews()
    return () => {
      cancelled = true
    }
  }, [attempt, symbol])

  if (state.isLoading) {
    return (
      <div className={pageStyles.contentSkeleton} aria-live="polite">Loading {symbol} source records…</div>
    )
  }

  if (state.error) {
    return (
      <div className={styles.statePanel} role="alert">
        <h2>News could not be loaded</h2>
        <p>{state.error}</p>
        <button className={styles.secondaryButton} onClick={() => setAttempt((value) => value + 1)} type="button">Try again</button>
      </div>
    )
  }

  const { news } = state

  return (
    <div className={styles.briefContent}>
      <header className={styles.newsHeader}>
        <h2>Source records</h2>
        <p>{news.length} {news.length === 1 ? "record" : "records"}</p>
      </header>
      {news.length > 0 ? <div className={styles.feedList}>{news.map((item) => (
        <AnnouncementCard item={item} key={item.id} />
      ))}</div> : (
        <div className={styles.statePanel}>
          <h2>No news available for {symbol}</h2>
          <p>The pipeline has not stored any announcements or publisher articles for this ticker yet.</p>
        </div>
      )}
    </div>
  )
}

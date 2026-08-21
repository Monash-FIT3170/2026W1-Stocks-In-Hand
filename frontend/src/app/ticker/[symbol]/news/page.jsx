"use client"

import { useEffect, useState } from "react"
import { AnnouncementCard } from "../../../components/announcements/AnnouncementCard"
import { AppFrame } from "../../../components/layout/AppFrame"
import { BriefAside } from "../../../components/ticker/BriefAside"
import { BriefTabs } from "../../../components/ticker/BriefTabs"
import { TickerHeader } from "../../../components/ticker/TickerHeader"
import { fetchTickerBriefAside, fetchTickerNews, fetchTickerOverview } from "../../../lib/api"
import styles from "../../../page.module.css"

// Ticker brief news tab for "/ticker/[symbol]/news".
// This reuses AnnouncementCard and renders only DB-backed ticker announcements.
export default function TickerNewsRoute({ params }) {
  const symbol = params.symbol.toUpperCase()
  const [state, setState] = useState({
    aside: null,
    error: false,
    isLoading: true,
    news: [],
    overview: null,
  })

  useEffect(() => {
    let cancelled = false

    async function loadNews() {
      try {
        const [news, overview, aside] = await Promise.all([
          fetchTickerNews(symbol),
          fetchTickerOverview(symbol),
          fetchTickerBriefAside(symbol),
        ])
        if (!cancelled) {
          setState({ aside, error: false, isLoading: false, news, overview })
        }
      } catch {
        if (!cancelled) {
          setState({ aside: null, error: true, isLoading: false, news: [], overview: null })
        }
      }
    }

    loadNews()
    return () => {
      cancelled = true
    }
  }, [symbol])

  if (state.isLoading) {
    return (
      <AppFrame active="home">
        <section className={styles.contentPage}>
          <div className={styles.emptyCard}><h3>Loading {symbol} news...</h3></div>
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

  const { news, overview, aside } = state

  return (
    <AppFrame active="home">
      <section className={styles.contentPage}>
        <div className={styles.briefShell}>
          <div className={styles.briefMain}>
            <TickerHeader data={overview} />
            <BriefTabs active="news" symbol={symbol} />
            <div className={styles.briefContent}>
              {news.map((item) => (
                <AnnouncementCard item={item} key={item.id} />
              ))}
            </div>
          </div>
          <BriefAside data={aside} />
        </div>
      </section>
    </AppFrame>
  )
}

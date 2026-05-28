"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { AppFrame } from "./components/layout/AppFrame"
import { BadgeIcon, BellIcon, CalendarIcon, SearchIcon } from "./components/icons"
import { fetchTickers } from "./lib/api"
import styles from "./page.module.css"

// Landing page route for "/".
// This file should stay focused on the first-screen marketing/search experience:
// hero copy, the landing search form, popular ticker links, and feature-card layout.
// Shared navigation/footer changes belong in AppFrame.jsx.
const iconMap = { calendar: CalendarIcon, bell: BellIcon, badge: BadgeIcon }
const features = [
  {
    icon: "calendar",
    tone: "mint",
    title: "Daily briefs in plain English",
    body: "Complex regulatory filings translated into clear, actionable summaries every morning.",
    featured: false,
  },
  {
    icon: "bell",
    tone: "amber",
    title: "Alerts when it matters",
    body: "Skip the noise. Get notified only when price-sensitive news or significant sentiment shifts occur.",
    featured: false,
  },
  {
    icon: "badge",
    tone: "sage",
    title: "Every claim is sourced",
    body: "Zero hallucinations. Every insight includes direct links to official ASX announcements or verified data.",
    featured: true,
  },
]

export default function Home() {
  const [query, setQuery] = useState("BHP")
  const [popularStocks, setPopularStocks] = useState(null)

  useEffect(() => {
    let ignore = false

    fetchTickers({ limit: 6 })
      .then((tickers) => {
        if (!ignore) {
          setPopularStocks(tickers.map((ticker) => ticker.symbol).filter(Boolean))
        }
      })
      .catch(() => {
        if (!ignore) {
          setPopularStocks([])
        }
      })

    return () => {
      ignore = true
    }
  }, [])

  function handleSearch(event) {
    event.preventDefault()
    window.location.href = `/search?q=${encodeURIComponent(query.trim() || "BHP")}`
  }

  const popularTickerLinks = popularStocks === null
    ? <span>Loading tickers</span>
    : popularStocks.length > 0
      ? popularStocks.map((ticker) => <Link key={ticker} href={`/search?q=${ticker}`}>{ticker}</Link>)
      : <span>No tickers loaded</span>

  return (
    <AppFrame active="home">
      <section className={styles.homePage}>
        <div className={styles.hero}>
          <h1>Understand any ASX stock<span>in <em>60 seconds</em></span></h1>
          <p>We read every announcement, news article, and investor forum so you don&apos;t have to. Real-time clarity for the modern investor.</p>
          <form className={styles.heroSearch} onSubmit={handleSearch}>
            <SearchIcon />
            <input aria-label="Search a company or ticker" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search a company or ticker - e.g. BHP, CSL, CBA" />
          </form>
          <div className={styles.popularRow}>
            <span>Popular:</span>
            {popularTickerLinks}
          </div>
        </div>

        <div className={styles.featureGrid}>
          {features.map((feature) => {
            const Icon = iconMap[feature.icon]
            return (
              <article className={`${styles.featureCard} ${feature.featured ? styles.featureCardHighlighted : ""}`} key={feature.title}>
                <div className={`${styles.iconBubble} ${styles[feature.tone]}`}><Icon /></div>
                <h2>{feature.title}</h2>
                <p>{feature.body}</p>
              </article>
            )
          })}
        </div>
      </section>
    </AppFrame>
  )
}

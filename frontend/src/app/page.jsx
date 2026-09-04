"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
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
    title: "Briefs in plain English",
    body: "Supported regulatory filings are organised into concise summaries with the original context kept close by.",
    featured: false,
  },
  {
    icon: "bell",
    tone: "amber",
    title: "Material updates in focus",
    body: "Scan recent company filings and publisher reports without treating every update as an investment signal.",
    featured: false,
  },
  {
    icon: "badge",
    tone: "sage",
    title: "Source-aware by design",
    body: "Insights show the linked ASX announcement or publisher record used to prepare the brief when that source is available.",
    featured: true,
  },
]

export default function Home() {
  const router = useRouter()
  const [query, setQuery] = useState("")
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
    const nextQuery = query.trim()
    router.push(nextQuery ? `/search?q=${encodeURIComponent(nextQuery)}` : "/search")
  }

  const popularTickerLinks = popularStocks === null
    ? <span>Loading tickers</span>
    : popularStocks.length > 0
      ? popularStocks.map((ticker) => <Link key={ticker} href={`/ticker/${ticker}`}>{ticker}</Link>)
      : <span>No tickers loaded</span>

  return (
    <section className={styles.homePage}>
        <div className={styles.hero}>
          <h1>Understand any ASX stock{" "}<span>in <em>60 seconds</em></span></h1>
          <p>Explore supported ASX filings and publisher reports as concise, source-aware company briefs.</p>
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
  )
}

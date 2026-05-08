"use client"

import Link from "next/link"
import { useState } from "react"
import { AppFrame } from "./components/layout/AppFrame"
import { BadgeIcon, BellIcon, CalendarIcon, SearchIcon } from "./components/icons"
import { features, popularStocks } from "./mock/landing"
import styles from "./page.module.css"

const iconMap = { calendar: CalendarIcon, bell: BellIcon, badge: BadgeIcon }

export default function Home() {
  const [query, setQuery] = useState("BHP")

  function handleSearch(event) {
    event.preventDefault()
    window.location.href = `/search?q=${encodeURIComponent(query.trim() || "BHP")}`
  }

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
            {popularStocks.map((ticker) => <Link key={ticker} href={`/search?q=${ticker}`}>{ticker}</Link>)}
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

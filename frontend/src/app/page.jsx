"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { SearchIcon } from "./components/icons"
import { ArrowIcon, DocumentIcon } from "./components/company/CompanyPrimitives"
import { displayDate } from "./components/company/companyFormat"
import { companyRoute, meaningfulText, originalUrl, sourceKind } from "./components/announcements/recordPresentation"
import { fetchAnnouncements, fetchTickers } from "./lib/api"
import styles from "./page.module.css"

// Landing page route for "/".
// This file should stay focused on the first-screen marketing/search experience:
// hero copy, the landing search form, popular ticker links, and feature-card layout.
// Shared navigation/footer changes belong in AppFrame.jsx.
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
  const [sourceRecord, setSourceRecord] = useState(null)
  const [sourceLoaded, setSourceLoaded] = useState(false)

  useEffect(() => {
    let ignore = false

    fetchTickers({ limit: 6 })
      .then((tickers) => {
        if (!ignore) {
          setPopularStocks(tickers.map((ticker) => ticker.symbol).filter((symbol) => companyRoute(symbol)))
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

  useEffect(() => {
    let ignore = false
    fetchAnnouncements({ limit: 1 })
      .then((records) => { if (!ignore) setSourceRecord(records[0] || null) })
      .catch(() => {})
      .finally(() => { if (!ignore) setSourceLoaded(true) })
    return () => { ignore = true }
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
          <div className={styles.heroIntro}>
          <h1>Understand any ASX stock{" "}<span>in 60 seconds</span></h1>
          <p>Explore supported ASX filings and publisher reports as concise, source-aware company briefs.</p>
          <form className={styles.heroSearch} onSubmit={handleSearch}>
            <SearchIcon />
            <input aria-label="Search a company or ticker" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search a company or ticker - e.g. BHP, CSL, CBA" />
            <button className={styles.searchSubmit} type="submit">Search</button>
          </form>
          <div className={styles.popularRow}>
            <span>Explore:</span>
            {popularTickerLinks}
          </div>
          </div>
          <section className={styles.heroExhibit} aria-label="Recent source material">
            <div className={styles.exhibitHeading}><h2>Research starts here.</h2><Link href="/announcements">Market feed<ArrowIcon /></Link></div>
            {sourceRecord?.is_preview && <p className={styles.previewNotice}>Local preview · Illustrative source record</p>}
            {sourceRecord ? <>
              <div className={styles.exhibitMeta}><DocumentIcon /><span>{sourceKind(sourceRecord.source_type || sourceRecord.tag)}</span><span>{sourceRecord.ticker === "ASX" ? "Market-wide" : sourceRecord.ticker}</span></div>
              <h3>{sourceRecord.title}</h3>
              {meaningfulText(sourceRecord.about, sourceRecord.title) && <p className={styles.exhibitExcerpt}>{sourceRecord.about}</p>}
              <dl className={styles.exhibitLedger}><div><dt>Source</dt><dd>{sourceRecord.source_name || "Source record"}</dd></div><div><dt>Published</dt><dd>{displayDate(sourceRecord.published_at)}</dd></div><div><dt>Analysis</dt><dd>{meaningfulText(sourceRecord.about, sourceRecord.title) ? "AI-assisted context" : "Summary pending"}</dd></div></dl>
              {originalUrl(sourceRecord.url) ? <a className={styles.exhibitAction} href={originalUrl(sourceRecord.url)} target="_blank" rel="noopener noreferrer">Open original source<ArrowIcon /></a> : <Link className={styles.exhibitAction} href="/announcements">Inspect source records<ArrowIcon /></Link>}
            </> : <>
              <h3>From the company update to the original evidence.</h3><p className={styles.exhibitExcerpt}>{sourceLoaded ? "Explore supported filings, publisher coverage and public discussion in one source-aware workflow." : "Loading recent source material…"}</p>
              <dl className={styles.exhibitLedger}><div><dt>Find</dt><dd>A company or update</dd></div><div><dt>Understand</dt><dd>Its stored research</dd></div><div><dt>Verify</dt><dd>The original material</dd></div></dl><Link className={styles.exhibitAction} href="/data-sources">Explore our sources<ArrowIcon /></Link>
            </>}
          </section>
        </div>

        <section className={styles.featureSection} aria-label="How the research works">
        <div className={styles.featureGrid}>
          {features.map((feature) => {
            return (
              <article className={`${styles.featureCard} ${feature.featured ? styles.featureCardHighlighted : ""}`} key={feature.title}>
                <h2>{feature.title}</h2>
                <p>{feature.body}</p>
              </article>
            )
          })}
        </div>
        </section>
    </section>
  )
}

"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { fetchCurrentInvestor, fetchWatchlistSummary } from "../../lib/api"
import { watchlistCard } from "../../lib/watchlists"
import styles from "../../page.module.css"

const EMPTY_STATE = { investor: null, companies: [], isLoading: false, error: "" }

export function HomeWatchlist({ investor, companies, isLoading, error, onRetry }) {
  if (!investor) return null

  return (
    <section aria-labelledby="home-watchlist-title" className={styles.homeWatchlist}>
      <div className={styles.homeWatchlistHeader}>
        <div>
          <h2 id="home-watchlist-title">My watchlist</h2>
          <p>Recent briefs and sentiment for your saved ASX companies.</p>
        </div>
        <Link className={styles.secondaryButton} href="/watchlist">Manage watchlist</Link>
      </div>
      {isLoading && <p role="status">Loading your watchlist…</p>}
      {error && <div className={styles.emptyCard} role="alert"><p>{error}</p><button className={styles.secondaryButton} onClick={onRetry} type="button">Try again</button></div>}
      {!isLoading && !error && <div className={styles.watchGrid}>
        {companies.map((company) => {
          const card = watchlistCard(company)
          return (
            <article className={styles.stockCard} key={company.ticker_id}>
              <Link className={styles.stockCardLink} href={`/ticker/${company.symbol}`}>
                <div className={styles.stockTop}><div><h3>{company.company_name}</h3><p>{company.exchange}: {company.symbol}</p></div></div>
                <div className={`${styles.stockStatus} ${styles[card.tone]}`}><span /> {card.status}</div>
                {card.brief && <p className={styles.stockBrief}>{card.brief}</p>}
                <div className={styles.stockFooter}><span>Last brief: {card.lastBrief}</span><strong>&gt;</strong></div>
              </Link>
            </article>
          )
        })}
        {!companies.length && <div className={styles.emptyCard}><h3>No companies yet</h3><p>Add a company to start your watchlist.</p><Link className={styles.secondaryButton} href="/watchlist">Add company</Link></div>}
      </div>}
    </section>
  )
}

export function HomeWatchlistSection() {
  const [state, setState] = useState(EMPTY_STATE)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function loadWatchlist() {
      try {
        const investor = await fetchCurrentInvestor()
        if (cancelled || !investor) return
        setState({ ...EMPTY_STATE, investor, isLoading: true })
        const summary = await fetchWatchlistSummary()
        if (!cancelled) setState({ investor, companies: summary.companies, isLoading: false, error: "" })
      } catch (error) {
        if (!cancelled) setState((current) => error.status === 401
          ? EMPTY_STATE
          : { ...current, isLoading: false, error: "Your watchlist is unavailable right now. Check your connection and try again." })
      }
    }

    function refreshWatchlist() {
      cancelled = true
      setState(EMPTY_STATE)
      setAttempt((current) => current + 1)
    }

    loadWatchlist()
    window.addEventListener("stonks-auth-changed", refreshWatchlist)
    return () => {
      cancelled = true
      window.removeEventListener("stonks-auth-changed", refreshWatchlist)
    }
  }, [attempt])

  function retry() {
    setState(EMPTY_STATE)
    setAttempt((current) => current + 1)
  }

  return <HomeWatchlist {...state} onRetry={retry} />
}

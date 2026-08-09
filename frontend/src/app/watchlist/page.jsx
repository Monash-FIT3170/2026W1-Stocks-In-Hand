"use client"

import Link from "next/link"
import { useCallback, useEffect, useMemo, useState } from "react"
import { AppFrame } from "../components/layout/AppFrame"
import { PlusIcon } from "../components/icons"
import { apiFetch } from "../lib/api"
import styles from "../page.module.css"

function getErrorMessage(data, fallback) {
  if (Array.isArray(data.detail)) {
    return data.detail.map((error) => error.msg).join(", ")
  }

  if (typeof data.detail === "string") {
    return data.detail
  }

  return fallback
}

async function fetchJson(path, fallback, options = {}) {
  const response = await apiFetch(path, {
    credentials: "include",
    ...options,
  })
  const data = await response.json().catch(() => null)

  if (response.status === 404 && fallback !== undefined) {
    return fallback
  }

  if (!response.ok) {
    throw new Error(getErrorMessage(data || {}, "Could not load watchlist"))
  }

  return data
}

function getStatusTone(status) {
  const value = status.toLowerCase()
  if (value.includes("negative") || value.includes("bearish") || value.includes("critical")) {
    return "red"
  }

  if (value.includes("positive") || value.includes("bullish") || value.includes("high conviction")) {
    return "green"
  }

  return "orange"
}

function formatStatusLabel(value) {
  const cleaned = value.replace(/[_-]/g, " ").trim()
  if (!cleaned) {
    return "Monitoring"
  }

  const label = cleaned.replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
  return label.toLowerCase().includes("sentiment") ? label : `${label} Sentiment`
}

function getStockBrief(stock) {
  const about = stock.latestArtifact?.artifact_metadata?.about
  if (about && typeof about === "string") {
    return about.length > 150 ? `${about.slice(0, 147)}...` : about
  }
  return null
}

function getTickerStatus(ticker) {
  if (ticker.latestSentiment?.sentiment_label) {
    return formatStatusLabel(ticker.latestSentiment.sentiment_label)
  }

  if (ticker.latestSentiment?.stance) {
    return formatStatusLabel(ticker.latestSentiment.stance)
  }

  if (ticker.sector) {
    return `${ticker.sector} Monitoring`
  }

  return "Monitoring"
}

function getArtifactDate(artifact) {
  return artifact?.published_at || artifact?.created_at || artifact?.scraped_at || null
}

function sortByNewestDate(items, getDate) {
  return [...items].sort((a, b) => new Date(getDate(b) || 0) - new Date(getDate(a) || 0))
}

function formatRelativeDate(value) {
  if (!value) {
    return "Not available"
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return "Not available"
  }

  const diffMs = Date.now() - date.getTime()
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffDays <= 0) {
    return "Today"
  }

  if (diffDays === 1) {
    return "Yesterday"
  }

  return `${diffDays} days ago`
}

async function findLatestSentiment(artifacts) {
  const recentArtifacts = sortByNewestDate(artifacts, getArtifactDate).slice(0, 5)

  for (const artifact of recentArtifacts) {
    const sentiments = await fetchJson(`/artifact-sentiments/artifact/${artifact.id}`, [])
    if (Array.isArray(sentiments) && sentiments.length) {
      return sortByNewestDate(sentiments, (sentiment) => sentiment.created_at)[0]
    }
  }

  return null
}

async function loadTickerDetails(watchlistTicker) {
  const ticker = await fetchJson(`/tickers/${watchlistTicker.ticker_id}`)
  const artifacts = await fetchJson(`/artifacts/ticker/${watchlistTicker.ticker_id}`, [])
  const sortedArtifacts = sortByNewestDate(artifacts, getArtifactDate)
  const latestArtifact = sortedArtifacts[0] || null
  const latestSentiment = await findLatestSentiment(sortedArtifacts)

  return {
    ...ticker,
    added_at: watchlistTicker.added_at,
    latestArtifact,
    latestSentiment,
    lastBriefAt: getArtifactDate(latestArtifact),
  }
}

export default function WatchlistRoute() {
  const [state, setState] = useState({
    error: "",
    investor: null,
    investorId: null,
    isLoading: true,
    tickers: [],
    watchlist: null,
  })
  const [isAddOpen, setIsAddOpen] = useState(false)
  const [availableTickers, setAvailableTickers] = useState([])
  const [tickerQuery, setTickerQuery] = useState("")
  const [addError, setAddError] = useState("")
  const [isTickerListLoading, setIsTickerListLoading] = useState(false)
  const [addingTickerId, setAddingTickerId] = useState(null)

  const loadWatchlist = useCallback(async ({ showLoading = false } = {}) => {
    if (showLoading) {
      setState((current) => ({ ...current, error: "", isLoading: true }))
    }

    try {
      const me = await fetchJson("/auth/me")
      const investor = me?.investor || null
      const investorId = investor?.id

      if (!investorId) {
        throw new Error("Could not identify the signed-in investor.")
      }

      const watchlists = await fetchJson(`/watchlists/investor/${investorId}`, [])
      const watchlist = watchlists[0] || null
      const watchlistTickers = watchlist
        ? await fetchJson(`/watchlist-tickers/${watchlist.id}`, [])
        : []
      const tickers = await Promise.all(
        watchlistTickers.map((item) => loadTickerDetails(item))
      )

      setState({
        error: "",
        investor,
        investorId,
        isLoading: false,
        tickers,
        watchlist,
      })
    } catch (err) {
      setState((current) => ({
        ...current,
        error:
          err instanceof TypeError
            ? "Could not reach the backend. Make sure the API is running on port 8000."
            : err.message,
        isLoading: false,
      }))
    }
  }, [])

  useEffect(() => {
    let isMounted = true

    loadWatchlist({ showLoading: true }).catch((err) => {
      if (isMounted) {
        setState((current) => ({
          ...current,
          error: err.message,
          isLoading: false,
        }))
      }
    })

    return () => {
      isMounted = false
    }
  }, [loadWatchlist])

  const watchedTickerIds = useMemo(
    () => new Set(state.tickers.map((ticker) => ticker.id)),
    [state.tickers]
  )
  const filteredAvailableTickers = useMemo(() => {
    const query = tickerQuery.trim().toLowerCase()

    return (Array.isArray(availableTickers) ? availableTickers : [])
      .filter((ticker) => {
        if (!query) {
          return true
        }

        return (
          ticker.symbol.toLowerCase().includes(query) ||
          ticker.company_name.toLowerCase().includes(query)
        )
      })
      .slice(0, 20)
  }, [availableTickers, tickerQuery])

  async function openAddCompany() {
    setIsAddOpen(true)
    setAddError("")

    if (availableTickers.length) {
      return
    }

    setIsTickerListLoading(true)
    try {
      const result = await fetchJson("/tickers/?limit=500", [])
      setAvailableTickers(Array.isArray(result) ? result : [])
    } catch (err) {
      setAddError(
        err instanceof TypeError
          ? "Could not reach the backend. Make sure the API is running on port 8000."
          : err.message
      )
    } finally {
      setIsTickerListLoading(false)
    }
  }

  function closeAddCompany() {
    setIsAddOpen(false)
    setTickerQuery("")
    setAddError("")
    setAddingTickerId(null)
  }

  async function ensureWatchlist() {
    if (state.watchlist) {
      return state.watchlist
    }

    if (!state.investorId) {
      throw new Error("Could not identify the signed-in investor.")
    }

    const watchlist = await fetchJson("/watchlists/", undefined, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        investor_id: state.investorId,
        name: "My Watchlist",
      }),
    })
    setState((current) => ({ ...current, watchlist }))
    return watchlist
  }

  async function addCompany(ticker) {
    setAddError("")
    setAddingTickerId(ticker.id)

    try {
      const watchlist = await ensureWatchlist()
      await fetchJson(`/watchlist-tickers/${watchlist.id}/${ticker.id}`, undefined, {
        method: "POST",
      })
      await loadWatchlist()
      closeAddCompany()
    } catch (err) {
      setAddError(
        err instanceof TypeError
          ? "Could not reach the backend. Make sure the API is running on port 8000."
          : err.message
      )
      setAddingTickerId(null)
    }
  }

  async function removeCompany(ticker) {
    if (!state.watchlist) return
    setState((current) => ({
      ...current,
      tickers: current.tickers.filter((t) => t.id !== ticker.id),
    }))
    try {
      await fetchJson(`/watchlist-tickers/${state.watchlist.id}/${ticker.id}`, undefined, {
        method: "DELETE",
      })
    } catch {
      await loadWatchlist()
    }
  }

  const investorName = state.investor?.username || state.investor?.email

  return (
    <AppFrame active="watchlist" signedIn={Boolean(state.investorId)}>
      <section className={styles.contentPage}>
        <div className={styles.watchlistHero}>
          <div>
            <h1>Portfolio Intel</h1>
            <p>{investorName ? `Monitoring ${investorName}'s saved ASX companies for structural shifts and sentiment swings.` : "Sign in to load your saved ASX portfolio from the database."}</p>
            <h2>Active Watchlist</h2>
          </div>
          <button className={styles.primaryAction} onClick={openAddCompany} type="button"><PlusIcon /> Add company</button>
        </div>
        <div className={styles.watchlistLayout}>
          <section>
            <div className={styles.watchlistCount}>
              {state.isLoading ? "Loading Watchlist" : `${state.tickers.length} Entities Tracking`}
            </div>
            <div className={styles.watchGrid}>
              {state.isLoading ? (
                <article className={styles.emptyCard}><h3>Loading watchlist</h3><p>Fetching your saved companies</p></article>
              ) : null}
              {state.error ? (
                <article className={styles.emptyCard}><h3>Could not load watchlist</h3><p>{state.error}</p></article>
              ) : null}
              {!state.isLoading && !state.error && state.tickers.map((stock) => {
                const status = getTickerStatus(stock)
                const tone = getStatusTone(status)

                return (
                  <article className={styles.stockCard} key={stock.id}>
                    <Link className={styles.stockCardLink} href={`/ticker/${stock.symbol}`}>
                      <div className={styles.stockTop}>
                        <div className={`${styles.stockAvatar} ${styles[tone]}`}>{stock.symbol[0]}</div>
                        <div><h3>{stock.company_name}</h3><p>{stock.exchange}: {stock.symbol}</p></div>
                      </div>
                      <div className={`${styles.stockStatus} ${styles[tone]}`}><span /> {status}</div>
                      {getStockBrief(stock) ? <p className={styles.stockBrief}>{getStockBrief(stock)}</p> : null}
                      <div className={styles.stockFooter}><span>Last brief: {formatRelativeDate(stock.lastBriefAt)}</span><strong>&gt;</strong></div>
                    </Link>
                    <button
                      aria-label={`Remove ${stock.symbol} from watchlist`}
                      className={styles.stockRemove}
                      onClick={() => removeCompany(stock)}
                      type="button"
                    >
                      ×
                    </button>
                  </article>
                )
              })}
              {!state.isLoading && !state.error && !state.tickers.length ? (
                <article className={styles.emptyCard}><h3>No companies yet</h3><p>Add a company to start monitoring</p></article>
              ) : null}
              <button className={styles.emptyCard} onClick={openAddCompany} type="button"><PlusIcon /><h3>Add to Watchlist</h3><p>Monitor your next move</p></button>
            </div>
          </section>
        </div>
        {isAddOpen ? (
          <div className={styles.watchlistModalBackdrop} role="presentation">
            <section aria-modal="true" className={styles.watchlistModal} role="dialog">
              <div className={styles.watchlistModalHeader}>
                <div>
                  <h2>Add Company</h2>
                  <p>Select an ASX company to monitor in your watchlist.</p>
                </div>
                <button aria-label="Close add company" onClick={closeAddCompany} type="button">x</button>
              </div>
              <label className={styles.watchlistSearch}>
                <span>Search companies</span>
                <input
                  autoFocus
                  onChange={(event) => setTickerQuery(event.target.value)}
                  placeholder="Search by ticker or company"
                  type="search"
                  value={tickerQuery}
                />
              </label>
              {addError ? <p className={styles.watchlistModalError}>{addError}</p> : null}
              <div className={styles.watchlistTickerList}>
                {isTickerListLoading ? <p>Loading companies...</p> : null}
                {!isTickerListLoading && filteredAvailableTickers.map((ticker) => {
                  const alreadyAdded = watchedTickerIds.has(ticker.id)
                  return (
                    <button
                      className={styles.watchlistTickerOption}
                      disabled={alreadyAdded || addingTickerId === ticker.id}
                      key={ticker.id}
                      onClick={() => addCompany(ticker)}
                      type="button"
                    >
                      <span><strong>{ticker.symbol}</strong>{ticker.company_name}</span>
                      <small>{alreadyAdded ? "Added" : addingTickerId === ticker.id ? "Adding..." : ticker.exchange}</small>
                    </button>
                  )
                })}
                {!isTickerListLoading && !filteredAvailableTickers.length && availableTickers.length === 0 ? (
                  <p>No companies in the database yet. The data pipeline may still be running.</p>
                ) : null}
                {!isTickerListLoading && !filteredAvailableTickers.length && availableTickers.length > 0 ? (
                  <p>No companies match your search.</p>
                ) : null}
              </div>
            </section>
          </div>
        ) : null}
      </section>
    </AppFrame>
  )
}

"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { AppFrame } from "../components/layout/AppFrame"
import { EyeIcon, PlusIcon } from "../components/icons"
import styles from "../page.module.css"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

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
  const response = await fetch(`${API_URL}${path}`, {
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

function getTickerStatus(ticker) {
  if (ticker.latestSentiment?.sentiment_label) {
    return formatStatusLabel(ticker.latestSentiment.sentiment_label)
  }

  if (ticker.latestSentiment?.stance) {
    return formatStatusLabel(ticker.latestSentiment.stance)
  }

  if (ticker.latestAlert?.severity) {
    return `${ticker.latestAlert.severity} Alert`
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

function alertTone(alert) {
  const value = `${alert.severity || ""} ${alert.alert_type || ""}`.toLowerCase()
  if (value.includes("high") || value.includes("critical") || value.includes("negative")) {
    return "red"
  }

  if (value.includes("medium") || value.includes("mixed") || value.includes("warning")) {
    return "orange"
  }

  return "green"
}

async function findLatestSentiment(artifacts) {
  const recentArtifacts = sortByNewestDate(
    artifacts.filter((artifact) => !artifact.is_duplicate),
    getArtifactDate
  ).slice(0, 5)

  for (const artifact of recentArtifacts) {
    const sentiments = await fetchJson(`/artifact-sentiments/artifact/${artifact.id}`, [])
    if (sentiments.length) {
      return sortByNewestDate(sentiments, (sentiment) => sentiment.created_at)[0]
    }
  }

  return null
}

async function loadTickerDetails(watchlistTicker) {
  const ticker = await fetchJson(`/tickers/${watchlistTicker.ticker_id}`)
  const [latestReport, artifacts] = await Promise.all([
    fetchJson(`/reports/ticker/${watchlistTicker.ticker_id}/latest`, null),
    fetchJson(`/artifacts/ticker/${watchlistTicker.ticker_id}`, []),
  ])
  const sortedArtifacts = sortByNewestDate(
    artifacts.filter((artifact) => !artifact.is_duplicate),
    getArtifactDate
  )
  const latestArtifact = sortedArtifacts[0] || null
  const latestSentiment = await findLatestSentiment(sortedArtifacts)

  return {
    ...ticker,
    added_at: watchlistTicker.added_at,
    latestArtifact,
    latestReport,
    latestSentiment,
    lastBriefAt: latestReport?.generated_at || getArtifactDate(latestArtifact),
  }
}

export default function WatchlistRoute() {
  const [state, setState] = useState({
    alerts: [],
    error: "",
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
      const investorId = me?.investor?.id

      if (!investorId) {
        throw new Error("Could not identify the signed-in investor.")
      }

      const watchlists = await fetchJson(`/watchlists/investor/${investorId}`, [])
      const watchlist = watchlists[0] || null
      const watchlistTickers = watchlist
        ? await fetchJson(`/watchlist-tickers/${watchlist.id}`, [])
        : []
      const [tickerDetails, alerts] = await Promise.all([
        Promise.all(
          watchlistTickers.map((item) => loadTickerDetails(item))
        ),
        fetchJson(`/alerts/investor/${investorId}`, []),
      ])

      const watchlistTickerIds = new Set(watchlistTickers.map((item) => item.ticker_id))
      const visibleAlerts = alerts
        .filter((alert) => watchlistTickerIds.has(alert.ticker_id))
        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))

      const tickers = tickerDetails.map((ticker) => {
        const tickerAlerts = visibleAlerts.filter((alert) => alert.ticker_id === ticker.id)
        return {
          ...ticker,
          alertCount: tickerAlerts.filter((alert) => !alert.is_read).length,
          latestAlert: tickerAlerts[0] || null,
        }
      })

      setState({
        alerts: visibleAlerts,
        error: "",
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

  const tickerSymbolsById = useMemo(
    () => new Map(state.tickers.map((ticker) => [ticker.id, ticker.symbol])),
    [state.tickers]
  )
  const watchedTickerIds = useMemo(
    () => new Set(state.tickers.map((ticker) => ticker.id)),
    [state.tickers]
  )
  const filteredAvailableTickers = useMemo(() => {
    const query = tickerQuery.trim().toLowerCase()

    return availableTickers
      .filter((ticker) => !watchedTickerIds.has(ticker.id))
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
  }, [availableTickers, tickerQuery, watchedTickerIds])

  async function openAddCompany() {
    setIsAddOpen(true)
    setAddError("")

    if (availableTickers.length) {
      return
    }

    setIsTickerListLoading(true)
    try {
      setAvailableTickers(await fetchJson("/tickers/?limit=500", []))
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

  return (
    <AppFrame active="watchlist" signedIn>
      <section className={styles.contentPage}>
        <div className={styles.watchlistHero}>
          <div>
            <h1>Portfolio Intel</h1>
            <p>Your personalized ASX guardian. We&apos;re monitoring your interests for structural shifts and sentiment swings.</p>
            <h2><EyeIcon /> Active Watchlist</h2>
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
                    <div className={styles.stockTop}>
                      <div className={`${styles.stockAvatar} ${styles[tone]}`}>{stock.symbol[0]}</div>
                      <div><h3>{stock.company_name}</h3><p>{stock.exchange}: {stock.symbol}</p></div>
                      {stock.alertCount ? <span className={styles.alertBadge}>{stock.alertCount}</span> : null}
                    </div>
                    <div className={`${styles.stockStatus} ${styles[tone]}`}><span /> {status}</div>
                    <div className={styles.stockFooter}><span>Last brief: {formatRelativeDate(stock.lastBriefAt)}</span><strong>&gt;</strong></div>
                  </article>
                )
              })}
              {!state.isLoading && !state.error && !state.tickers.length ? (
                <article className={styles.emptyCard}><h3>No companies yet</h3><p>Add a company to start monitoring</p></article>
              ) : null}
              <button className={styles.emptyCard} onClick={openAddCompany} type="button"><PlusIcon /><h3>Add to Watchlist</h3><p>Monitor your next move</p></button>
            </div>
          </section>
          <aside className={styles.alertsPanel}>
            <div className={styles.alertsHeader}><h2>Alerts Feed</h2><button type="button">Clear all</button></div>
            <div className={styles.alertTimeline}>
              {state.isLoading ? (
                <article className={styles.alertItem}>
                  <div className={`${styles.timelineDotSmall} ${styles.green}`} />
                  <div className={styles.alertCard}><span>Loading</span><p>Fetching recent alerts</p></div>
                </article>
              ) : null}
              {!state.isLoading && !state.error && state.alerts.map((alert) => (
                <article className={styles.alertItem} key={alert.id}>
                  <div className={`${styles.timelineDotSmall} ${styles[alertTone(alert)]}`} />
                  <div className={styles.alertCard}>
                    <span>{tickerSymbolsById.get(alert.ticker_id) || "ASX"} - {formatRelativeDate(alert.created_at)}</span>
                    <p>{alert.message || alert.title}</p>
                  </div>
                </article>
              ))}
              {!state.isLoading && !state.error && !state.alerts.length ? (
                <article className={styles.alertItem}>
                  <div className={`${styles.timelineDotSmall} ${styles.green}`} />
                  <div className={styles.alertCard}><span>No alerts</span><p>Your watchlist has no recent alerts.</p></div>
                </article>
              ) : null}
            </div>
            <button className={styles.historyButton} type="button">View History</button>
          </aside>
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
                {!isTickerListLoading && filteredAvailableTickers.map((ticker) => (
                  <button
                    className={styles.watchlistTickerOption}
                    disabled={addingTickerId === ticker.id}
                    key={ticker.id}
                    onClick={() => addCompany(ticker)}
                    type="button"
                  >
                    <span><strong>{ticker.symbol}</strong>{ticker.company_name}</span>
                    <small>{addingTickerId === ticker.id ? "Adding..." : ticker.exchange}</small>
                  </button>
                ))}
                {!isTickerListLoading && !filteredAvailableTickers.length ? (
                  <p>No available companies found.</p>
                ) : null}
              </div>
            </section>
          </div>
        ) : null}
      </section>
    </AppFrame>
  )
}

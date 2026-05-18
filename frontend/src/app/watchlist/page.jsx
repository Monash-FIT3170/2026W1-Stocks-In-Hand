import Link from "next/link"
import { cookies } from "next/headers"
import { AppFrame } from "../components/layout/AppFrame"
import { EyeIcon, PlusIcon } from "../components/icons"
import styles from "../page.module.css"

const API_URL = process.env.INTERNAL_API_URL || "http://backend:8000"

async function fetchJson(path, cookieHeader) {
  const response = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: cookieHeader ? { cookie: cookieHeader } : {},
  })

  if (response.status === 404 || response.status === 401) {
    return null
  }

  if (!response.ok) {
    throw new Error(`Failed to load ${path}`)
  }

  return response.json()
}

function formatAge(dateValue) {
  if (!dateValue) {
    return "recently"
  }

  const ageMs = Date.now() - new Date(dateValue).getTime()
  const days = Math.max(0, Math.floor(ageMs / 86_400_000))
  if (days === 0) {
    return "today"
  }
  if (days === 1) {
    return "1d ago"
  }
  return `${days}d ago`
}

function statusForTicker(ticker) {
  if (ticker.sector === "Financials") {
    return "Market Risk Watch"
  }
  if (ticker.sector === "Health Care") {
    return "Operational Momentum"
  }
  return "Database Tracking"
}

async function loadPortfolio() {
  const cookieHeader = cookies().toString()
  const auth = await fetchJson("/auth/me", cookieHeader)
  if (!auth?.investor) {
    return { investor: null, stocks: [], alerts: [] }
  }

  const watchlists = await fetchJson(`/watchlists/investor/${auth.investor.id}`, cookieHeader) || []
  const activeWatchlist = watchlists[0]
  const watchlistLinks = activeWatchlist
    ? await fetchJson(`/watchlist-tickers/${activeWatchlist.id}`, cookieHeader) || []
    : []

  const stocks = await Promise.all(
    watchlistLinks.map(async (item) => fetchJson(`/tickers/${item.ticker_id}`, cookieHeader))
  )
  const alerts = await fetchJson(`/alerts/investor/${auth.investor.id}`, cookieHeader) || []

  return {
    investor: auth.investor,
    stocks: stocks.filter(Boolean),
    alerts,
  }
}

export default async function WatchlistRoute() {
  const { investor, stocks, alerts } = await loadPortfolio()
  const alertCounts = alerts.reduce((counts, alert) => {
    counts[alert.ticker_id] = (counts[alert.ticker_id] || 0) + 1
    return counts
  }, {})
  const tickerById = new Map(stocks.map((stock) => [stock.id, stock]))

  return (
    <AppFrame active="watchlist" signedIn={Boolean(investor)}>
      <section className={styles.contentPage}>
        <div className={styles.watchlistHero}>
          <div>
            <h1>Portfolio Intel</h1>
            <p>{investor ? `Monitoring ${investor.username || investor.email}'s saved ASX companies for structural shifts and sentiment swings.` : "Sign in to load your saved ASX portfolio from the database."}</p>
            <h2><EyeIcon /> Active Watchlist</h2>
          </div>
          <button className={styles.primaryAction} type="button"><PlusIcon /> Add company</button>
        </div>
        <div className={styles.watchlistLayout}>
          <section>
            <div className={styles.watchlistCount}>{stocks.length} Entities Tracking</div>
            <div className={styles.watchGrid}>
              {stocks.map((stock) => (
                <Link className={styles.stockCard} href={`/ticker/${stock.symbol}`} key={stock.id}>
                  <div className={styles.stockTop}>
                    <div className={`${styles.stockAvatar} ${styles.green}`}>{stock.symbol[0]}</div>
                    <div><h3>{stock.company_name}</h3><p>{stock.exchange}: {stock.symbol}</p></div>
                    {alertCounts[stock.id] ? <span className={styles.alertBadge}>{alertCounts[stock.id]}</span> : null}
                  </div>
                  <div className={`${styles.stockStatus} ${styles.green}`}><span /> {statusForTicker(stock)}</div>
                  <div className={styles.stockFooter}><span>{stock.sector || stock.industry || "Portfolio company"}</span><strong>&gt;</strong></div>
                </Link>
              ))}
              <article className={styles.emptyCard}><PlusIcon /><h3>Add to Watchlist</h3><p>Monitor your next move</p></article>
            </div>
          </section>
          <aside className={styles.alertsPanel}>
            <div className={styles.alertsHeader}><h2>Alerts Feed</h2><button type="button">Clear all</button></div>
            <div className={styles.alertTimeline}>
              {alerts.map((alert) => {
                const ticker = tickerById.get(alert.ticker_id)
                const tone = alert.severity === "warning" ? styles.orange : alert.severity === "error" ? styles.red : styles.green
                return (
                <article className={styles.alertItem} key={alert.id}>
                  <div className={`${styles.timelineDotSmall} ${tone}`} />
                  <div className={styles.alertCard}><span>{ticker?.symbol || "Market"} - {formatAge(alert.created_at)}</span><p>{alert.message}</p></div>
                </article>
                )
              })}
              {alerts.length === 0 ? <p>No portfolio alerts are in the database yet.</p> : null}
            </div>
            <button className={styles.historyButton} type="button">View History</button>
          </aside>
        </div>
      </section>
    </AppFrame>
  )
}

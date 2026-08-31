import styles from "../research/ResearchSurface.module.css"
import { MetricCard } from "../ui/MetricCard"

// Shared header for ticker brief pages.
// Price and day change come from a live Yahoo quote on the overview endpoint, so they
// show "N/A" whenever that lookup fails rather than blocking the rest of the header.
export function TickerHeader({ data }) {
  if (!data) return null;

  return (
    <header className={styles.tickerHero}>
      <div className={styles.tickerIdentity}>
        <div>
          <div className={styles.tickerCodeLine}>
            <strong>{data.symbol}</strong>
            <span>ASX</span>
            <span>{data.sector || "Sector unavailable"}</span>
          </div>
          <h1>{data.company_name}</h1>
        </div>
        <div className={styles.tickerStatus}>
          <span className={styles.statusDot} aria-hidden="true" />
          <span>{data.sentiment_label || "Analysis pending"}</span>
          <span>·</span>
          <span>Updated {data.last_updated || "date unavailable"}</span>
        </div>
      </div>
      <div className={styles.tickerMetrics}>
        <MetricCard label="Current price" value={data.current_price} />
        <MetricCard label="Day change" value={data.day_change} />
      </div>
    </header>
  )
}

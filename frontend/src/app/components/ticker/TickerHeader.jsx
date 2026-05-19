import styles from "../../page.module.css"
import { MetricCard } from "../ui/MetricCard"

// Shared header for ticker brief pages.
// Displays the company identity, sentiment timestamp, and price cards used across
// all ticker tabs. The values are placeholders until company profile and market data
// are available; keep the layout here and move data fetching up into the route later.
export function TickerHeader({ data }) {
  if (!data) return null;
  
  return (
    <div className={styles.tickerHeader}>
      <div>
        <div className={styles.tickerLine}>
          <span className={styles.tickerPill}>{data.symbol}</span>
          <span>{data.sector}</span>
        </div>
        <h1>{data.company_name}</h1>
        <p>
          <span className={styles.statusDot} /> {data.sentiment_label} <b /> Last updated: {data.last_updated}
        </p>
      </div>
      <div className={styles.priceCards}>
        <MetricCard label="Current price" value={data.current_price} />
        <MetricCard label="Day change" value={data.day_change} />
      </div>
    </div>
  )
}
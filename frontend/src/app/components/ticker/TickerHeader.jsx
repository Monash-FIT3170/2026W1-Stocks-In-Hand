import styles from "../../page.module.css"
import { MetricCard } from "../ui/MetricCard"

// Shared header for ticker brief pages.
// Price and day change come from a live Yahoo quote on the overview endpoint, so they
// show "N/A" whenever that lookup fails rather than blocking the rest of the header.
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

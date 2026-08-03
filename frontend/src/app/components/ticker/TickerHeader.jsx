import styles from "../../page.module.css"

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
    </div>
  )
}

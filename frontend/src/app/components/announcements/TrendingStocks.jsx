import Link from "next/link"
import styles from "../research/ResearchSurface.module.css"

export function TrendingStocks({ stocks = [] }) {
  return (
    <section className={styles.trendingPanel}>
      <div className={styles.panelHeading}>
        <h2>Trending this week</h2>
        <p>Companies with the most source activity in the current seven-day window.</p>
      </div>
      <div className={styles.trendingList}>
        {stocks.length > 0
          ? stocks.map((item, index) => {
              const symbol = typeof item === "string" ? item : item.symbol
              const count = typeof item === "string" ? null : item.announcement_count
              return (
                <Link className={styles.trendItem} href={`/ticker/${symbol}`} key={symbol}>
                  <span className={styles.trendRank}>{String(index + 1).padStart(2, "0")}</span>
                  <span className={styles.trendSymbol}>{symbol}</span>
                  <span className={styles.trendTrack} aria-hidden="true"><span style={{ width: `${Math.max(24, 100 - index * 22)}%` }} /></span>
                  <span className={styles.trendCount}>{count ? `${count} ${count === 1 ? "update" : "updates"}` : "Active"}</span>
                </Link>
              )
            })
          : <p className={styles.trendEmpty}>No recent ticker activity for this range.</p>}
      </div>
    </section>
  )
}

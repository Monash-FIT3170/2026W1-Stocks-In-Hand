import Link from "next/link"
import { companyRoute } from "./recordPresentation"
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
              const count = typeof item === "string" ? null : item.count ?? item.announcement_count
              const href = companyRoute(symbol)
              if (!href) return null
              return (
                <Link className={styles.trendItem} href={href} key={symbol}>
                  <span className={styles.trendRank}>{String(index + 1).padStart(2, "0")}</span>
                  <span className={styles.trendSymbol}>{symbol}</span>
                  <span className={styles.trendCount}>{count ? `${count} ${count === 1 ? "update" : "updates"}` : "View research"}</span>
                </Link>
              )
            })
          : <p className={styles.trendEmpty}>No recent ticker activity for this range.</p>}
      </div>
    </section>
  )
}

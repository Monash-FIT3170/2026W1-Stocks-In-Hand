import Link from "next/link"
import styles from "../../page.module.css"

export function TrendingStocks({ stocks = [] }) {
  return (
    <div className={styles.trendingBox}>
      <span>Trending stocks</span>
      <div>
        {stocks.length > 0
          ? stocks.map((item, index) => {
              const symbol = typeof item === "string" ? item : item.symbol
              return <Link className={index === 0 ? styles.hotTicker : ""} href={`/ticker/${symbol}`} key={symbol}>{symbol}</Link>
            })
          : <span>No filings yet</span>}
      </div>
    </div>
  )
}

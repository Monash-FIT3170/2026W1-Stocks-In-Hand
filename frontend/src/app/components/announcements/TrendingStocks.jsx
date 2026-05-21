import styles from "../../page.module.css"

export function TrendingStocks({ stocks = [] }) {
  return (
    <div className={styles.trendingBox}>
      <span>Trending stocks</span>
      <div>
        {stocks.length > 0
          ? stocks.map((item, index) => {
              const symbol = typeof item === "string" ? item : item.symbol
              return <b className={index === 0 ? styles.hotTicker : ""} key={symbol}>{symbol}</b>
            })
          : <b>No filings yet</b>}
      </div>
    </div>
  )
}

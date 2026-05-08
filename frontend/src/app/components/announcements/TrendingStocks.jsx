import { trendingStocks } from "../../mock/announcements"
import styles from "../../page.module.css"

export function TrendingStocks() {
  return (
    <div className={styles.trendingBox}>
      <span>Trending stocks</span>
      <div>
        {trendingStocks.map((ticker, index) => <b className={index === 1 ? styles.hotTicker : ""} key={ticker}>{ticker}</b>)}
      </div>
    </div>
  )
}

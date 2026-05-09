import { trendingStocks } from "../../mock/announcements"
import styles from "../../page.module.css"

// Small sidebar module for the announcements page.
// The trend badges are sourced from mock/announcements.js so the list can be replaced
// by a market/trending endpoint without changing this component's markup.
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

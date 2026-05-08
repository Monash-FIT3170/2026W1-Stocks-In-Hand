import styles from "../../page.module.css"
import { MetricCard } from "../ui/MetricCard"

export function TickerHeader() {
  return (
    <div className={styles.tickerHeader}>
      <div>
        <div className={styles.tickerLine}><span className={styles.tickerPill}>BHP</span><span>Mining</span></div>
        <h1>BHP Group</h1>
        <p><span className={styles.statusDot} /> Generally Positive <b /> Last updated: 2 hours ago</p>
      </div>
      <div className={styles.priceCards}>
        <MetricCard label="Current price" value="$44.82" />
        <MetricCard label="Day change" value="+1.24%" />
      </div>
    </div>
  )
}

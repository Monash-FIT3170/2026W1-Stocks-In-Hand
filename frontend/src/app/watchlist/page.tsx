import { AppFrame } from "../components/layout/AppFrame"
import { EyeIcon, PlusIcon } from "../components/icons"
import { watchAlerts, watchlistStocks } from "../mock/watchlist"
import styles from "../page.module.css"

export default function WatchlistRoute() {
  return (
    <AppFrame active="watchlist" signedIn>
      <section className={styles.contentPage}>
        <div className={styles.watchlistHero}>
          <div>
            <h1>Portfolio Intel</h1>
            <p>Your personalized ASX guardian. We&apos;re monitoring your interests for structural shifts and sentiment swings.</p>
            <h2><EyeIcon /> Active Watchlist</h2>
          </div>
          <button className={styles.primaryAction} type="button"><PlusIcon /> Add company</button>
        </div>
        <div className={styles.watchlistLayout}>
          <section>
            <div className={styles.watchlistCount}>3 Entities Tracking</div>
            <div className={styles.watchGrid}>
              {watchlistStocks.map((stock) => (
                <article className={styles.stockCard} key={stock.ticker}>
                  <div className={styles.stockTop}>
                    <div className={`${styles.stockAvatar} ${styles[stock.color]}`}>{stock.ticker[0]}</div>
                    <div><h3>{stock.name}</h3><p>ASX: {stock.ticker}</p></div>
                    {stock.alerts ? <span className={styles.alertBadge}>{stock.alerts}</span> : null}
                  </div>
                  <div className={`${styles.stockStatus} ${styles[stock.color]}`}><span /> {stock.status}</div>
                  <div className={styles.stockFooter}><span>Last brief: {stock.ticker === "CBA" ? "2 days ago" : "Yesterday"}</span><strong>&gt;</strong></div>
                </article>
              ))}
              <article className={styles.emptyCard}><PlusIcon /><h3>Add to Watchlist</h3><p>Monitor your next move</p></article>
            </div>
          </section>
          <aside className={styles.alertsPanel}>
            <div className={styles.alertsHeader}><h2>Alerts Feed</h2><button type="button">Clear all</button></div>
            <div className={styles.alertTimeline}>
              {watchAlerts.map((alert, index) => (
                <article className={styles.alertItem} key={alert}>
                  <div className={`${styles.timelineDotSmall} ${index === 1 ? styles.orange : index === 2 ? styles.red : styles.green}`} />
                  <div className={styles.alertCard}><span>{index === 3 ? "Market" : watchlistStocks[index]?.ticker} - {index + 1}d ago</span><p>{alert}</p></div>
                </article>
              ))}
            </div>
            <button className={styles.historyButton} type="button">View History</button>
          </aside>
        </div>
      </section>
    </AppFrame>
  )
}

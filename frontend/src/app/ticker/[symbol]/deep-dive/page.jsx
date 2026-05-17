import { AppFrame } from "../../../components/layout/AppFrame"
import { BriefAside } from "../../../components/ticker/BriefAside"
import { BriefTabs } from "../../../components/ticker/BriefTabs"
import { TickerHeader } from "../../../components/ticker/TickerHeader"
// import { timelineItems } from "../../../mock/ticker"
import styles from "../../../page.module.css"

// Ticker brief deep-dive tab for "/ticker/[symbol]/deep-dive".
// The filter chips are static visual controls for now. Timeline entries come from
// mock/ticker.js and can later be replaced by company event history data, keeping
// this page responsible for the timeline layout and interaction state.
async function fetchDeepDive(symbol) {
  const res = await fetch(`http://backend:8000/tickers/symbol/${symbol}/deep-dive-timeline`, { cache: 'no-store' })
  const overview = await fetch(`http://backend:8000/tickers/symbol/${symbol}/overview`, { cache: 'no-store' })
  if (!res.ok || !overview.ok) throw new Error("Failed to load data")
  return { timeline: await res.json(), overview: await overview.json() }
}

export default async function TickerDeepDiveRoute({ params }) {
  const symbol = params.symbol
  const { timeline, overview } = await fetchDeepDive(symbol)

  return (
    <AppFrame active="home">
      <section className={styles.contentPage}>
        <div className={styles.briefShell}>
          <div className={styles.briefMain}>
            <TickerHeader data={overview} />
            <BriefTabs active="deep" symbol={symbol} />
            <div className={styles.timelineShell}>
              <div className={styles.filterTabs}>
                {["All", "Strategic Update", "Regulatory"].map((label, index) => (
                  <button className={index === 0 ? styles.selectedChip : ""} key={label} type="button">{label}</button>
                ))}
              </div>
              <div className={styles.timeline}>
                {timeline.map((item) => (
                  <article className={styles.timelineItem} key={item.title}>
                    <span className={`${styles.timelineDot} ${styles[item.tone]}`} />
                    <div className={styles.timelineMonth}>{item.month}</div>
                    <div className={styles.timelineCard}>
                      <div className={styles.timelineTop}>
                        <span className={styles.softPill}>{item.tag}</span>
                        <strong>{item.date}</strong>
                      </div>
                      <h2>{item.title}</h2>
                      {item.metrics.length > 0 && (
                        <div className={styles.metricGrid}>
                          {item.metrics.map((metric) => <span key={metric}>{metric}</span>)}
                        </div>
                      )}
                      <p>{item.detail}</p>
                      <a href="#">View source</a>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </div>
          <BriefAside />
        </div>
      </section>
    </AppFrame>
  )
}

import { AppFrame } from "../../../components/layout/AppFrame"
import { BriefAside } from "../../../components/ticker/BriefAside"
import { BriefTabs } from "../../../components/ticker/BriefTabs"
import { TickerHeader } from "../../../components/ticker/TickerHeader"
import { timelineItems } from "../../../mock/ticker"
import styles from "../../../page.module.css"

// Ticker brief deep-dive tab for "/ticker/[symbol]/deep-dive".
// The filter chips are static visual controls for now. Timeline entries come from
// mock/ticker.js and can later be replaced by company event history data, keeping
// this page responsible for the timeline layout and interaction state.
export default function TickerDeepDiveRoute() {
  return (
    <AppFrame active="home">
      <section className={styles.contentPage}>
        <div className={styles.briefShell}>
          <div className={styles.briefMain}>
            <TickerHeader />
            <BriefTabs active="deep" />
            <div className={styles.timelineShell}>
              <div className={styles.filterTabs}>
                {["All", "Earnings", "Legal", "Leadership", "Announcements"].map((label, index) => <button className={index === 0 ? styles.selectedChip : ""} key={label} type="button">{label}</button>)}
              </div>
              <div className={styles.timeline}>
                {timelineItems.map((item) => (
                  <article className={styles.timelineItem} key={item.title}>
                    <span className={`${styles.timelineDot} ${styles[item.tone]}`} />
                    <div className={styles.timelineMonth}>{item.month}</div>
                    <div className={styles.timelineCard}>
                      <div className={styles.timelineTop}><span className={styles.softPill}>{item.tag}</span><strong>{item.date}</strong></div>
                      <h2>{item.title}</h2>
                      {item.metrics.length > 0 && <div className={styles.metricGrid}>{item.metrics.map((metric) => <span key={metric}>{metric}</span>)}</div>}
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

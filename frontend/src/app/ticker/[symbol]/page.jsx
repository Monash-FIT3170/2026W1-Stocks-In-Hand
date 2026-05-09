import { AppFrame } from "../../components/layout/AppFrame"
import { SparkIcon } from "../../components/icons"
import { BriefAside } from "../../components/ticker/BriefAside"
import { BriefTabs } from "../../components/ticker/BriefTabs"
import { TickerHeader } from "../../components/ticker/TickerHeader"
import styles from "../../page.module.css"

// Ticker brief summary tab for "/ticker/[symbol]".
// The folder is dynamic so the app structure is ready for different tickers, but
// the rendered prototype currently uses BHP placeholder content. TickerHeader,
// BriefTabs, and BriefAside are shared with the other ticker tabs; keep tab-specific
// summary content in this file unless it becomes reusable across multiple tabs.
export default function TickerSummaryRoute() {
  return (
    <AppFrame active="home">
      <section className={styles.contentPage}>
        <div className={styles.briefShell}>
          <div className={styles.briefMain}>
            <TickerHeader />
            <BriefTabs active="summary" />
            <div className={styles.briefContent}>
              <article className={styles.storyCard}>
                <div className={styles.storyHeading}><h2><SparkIcon /> What&apos;s the story?</h2><span>Daily</span></div>
                <p>BHP had a strong quarter with iron ore production up 8%. Analysts from major institutions are cautiously optimistic about the maintained full-year guidance, though there&apos;s growing chatter regarding persistent labor cost pressures in Western Australia. The strategic pivot toward copper and potash continues with the Jansen project progressing ahead of schedule.</p>
                <strong>AI Insight verified by 12 official sources</strong>
              </article>
              <article className={styles.sentimentCard}>
                <h2>Positive Sentiment</h2>
                <p>Today&apos;s announcements suggest a strong rebound in the mining sector, countered by cautious capital management in financials.</p>
                <div className={styles.sentimentBar}><span>Public Sentiment</span><strong>68%</strong></div>
              </article>
            </div>
          </div>
          <BriefAside />
        </div>
      </section>
    </AppFrame>
  )
}

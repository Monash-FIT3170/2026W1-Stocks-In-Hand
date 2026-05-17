import { AppFrame } from "../../components/layout/AppFrame"
import { SparkIcon } from "../../components/icons"
import { BriefAside } from "../../components/ticker/BriefAside"
import { BriefTabs } from "../../components/ticker/BriefTabs"
import { CitationLinks } from "../../components/ticker/CitationLinks"
import { TickerHeader } from "../../components/ticker/TickerHeader"
import styles from "../../page.module.css"

// Ticker brief summary tab for "/ticker/[symbol]".
// The folder is dynamic so the app structure is ready for different tickers, but
// the rendered prototype currently uses BHP placeholder content. TickerHeader,
// BriefTabs, and BriefAside are shared with the other ticker tabs; keep tab-specific
// summary content in this file unless it becomes reusable across multiple tabs.
async function fetchOverview(symbol) {
  const res = await fetch(`http://backend:8000/tickers/symbol/${symbol}/overview`, { cache: 'no-store' })
  if (!res.ok) throw new Error("Failed to load overview data")
  return res.json()
}

export default async function TickerSummaryRoute({ params }) {
  const symbol = params.symbol
  const data = await fetchOverview(symbol)

  return (
    <AppFrame active="home">
      <section className={styles.contentPage}>
        <div className={styles.briefShell}>
          <div className={styles.briefMain}>
            <TickerHeader data={data} />
            <BriefTabs active="summary" symbol={symbol} />
            <div className={styles.briefContent}>
              <article className={styles.storyCard}>
                <div className={styles.storyHeading}>
                  <h2><SparkIcon /> What&apos;s the story?</h2>
                  <span>Daily</span>
                </div>
                <p>{data.story}</p>
                <strong>AI Insight verified by {data.sources_count} official sources</strong>
                <CitationLinks sources={data.sources} />
              </article>
              <article className={styles.sentimentCard}>
                <h2>{data.sentiment_label}</h2>
                <p>Current announcements indicate healthy progression, balancing minor macroeconomic shifts seen across related sectors.</p>
                <div className={styles.sentimentBar}>
                  <span>Public Sentiment</span>
                  <strong>{data.public_sentiment_pct}</strong>
                </div>
              </article>
            </div>
          </div>
          <BriefAside />
        </div>
      </section>
    </AppFrame>
  )
}

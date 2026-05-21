import { AppFrame } from "../../components/layout/AppFrame"
import { SparkIcon } from "../../components/icons"
import { BriefAside } from "../../components/ticker/BriefAside"
import { BriefTabs } from "../../components/ticker/BriefTabs"
import { CitationLinks } from "../../components/ticker/CitationLinks"
import { TickerHeader } from "../../components/ticker/TickerHeader"
import { fetchTickerBriefAside, fetchTickerOverview } from "../../lib/api"
import styles from "../../page.module.css"

// Ticker brief summary tab for "/ticker/[symbol]".
// This route renders only DB-backed ticker overview data so missing data is visible
// during MVP testing.
export default async function TickerSummaryRoute({ params }) {
  const symbol = params.symbol
  let data, aside
  try {
    ;[data, aside] = await Promise.all([
      fetchTickerOverview(symbol),
      fetchTickerBriefAside(symbol),
    ])
  } catch {
    return (
      <AppFrame active="home">
        <section className={styles.contentPage}>
          <div className={styles.emptyCard}>
            <h3>{symbol} not found</h3>
            <p>This ticker is not in the database yet. It will appear once the data pipeline has run.</p>
          </div>
        </section>
      </AppFrame>
    )
  }

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
                <p>
                  Current saved signals are classified as {(data.sentiment_label || "neutral").toLowerCase()}.
                  Public sentiment coverage is {data.public_sentiment_pct}.
                </p>
                <div className={styles.sentimentBar}>
                  <span>Public Sentiment</span>
                  <strong>{data.public_sentiment_pct}</strong>
                </div>
              </article>
            </div>
          </div>
          <BriefAside data={aside} />
        </div>
      </section>
    </AppFrame>
  )
}

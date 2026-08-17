"use client"

import { useEffect, useState } from "react"
import { AppFrame } from "../../components/layout/AppFrame"
import { SparkIcon } from "../../components/icons"
import { BriefAside } from "../../components/ticker/BriefAside"
import { BriefTabs } from "../../components/ticker/BriefTabs"
import { CategorySentiment } from "../../components/ticker/CategorySentiment"
import { CitationLinks } from "../../components/ticker/CitationLinks"
import { TickerHeader } from "../../components/ticker/TickerHeader"
import { fetchTickerBriefAside, fetchTickerCategorySentiment, fetchTickerOverview } from "../../lib/api"
import styles from "../../page.module.css"

// Ticker brief summary tab for "/ticker/[symbol]".
// This route renders only DB-backed ticker overview data so missing data is visible
// during MVP testing.
export default function TickerSummaryRoute({ params }) {
  const symbol = params.symbol.toUpperCase()
  const [state, setState] = useState({
    aside: null,
    categorySentiment: null,
    data: null,
    error: false,
    isLoading: true,
  })

  useEffect(() => {
    let cancelled = false

    async function loadTicker() {
      try {
        const [data, aside, categorySentiment] = await Promise.all([
          fetchTickerOverview(symbol),
          fetchTickerBriefAside(symbol),
          fetchTickerCategorySentiment(symbol).catch((error) => ({
            unavailable: true,
            message: error.message,
          })),
        ])
        if (!cancelled) {
          setState({ aside, categorySentiment, data, error: false, isLoading: false })
        }
      } catch {
        if (!cancelled) {
          setState({ aside: null, categorySentiment: null, data: null, error: true, isLoading: false })
        }
      }
    }

    loadTicker()
    return () => {
      cancelled = true
    }
  }, [symbol])

  if (state.isLoading) {
    return (
      <AppFrame active="home">
        <section className={styles.contentPage}>
          <div className={styles.emptyCard}><h3>Loading {symbol}...</h3></div>
        </section>
      </AppFrame>
    )
  }

  if (state.error) {
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

  const { data, aside, categorySentiment } = state

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
                <div className={styles.sentimentHeader}>
                  <div>
                    <span className={styles.sentimentEyebrow}>Market Sentiment</span>
                    <h2>{data.sentiment_label || "Neutral"}</h2>
                  </div>

                  <strong className={styles.sentimentScore}>
                    {data.public_sentiment_pct || "N/A"}
                  </strong>
                </div>

                <p>
                  Current saved signals are classified as{" "}
                  {(data.sentiment_label || "neutral").toLowerCase()}.
                </p>

                <div className={styles.sentimentBar}>
                  <span>Public Sentiment</span>
                  <strong>{data.public_sentiment_pct || "N/A"}</strong>
                </div>

                <div className={styles.analysisSection}>
                  <h3>Key Risks</h3>

                  {data.risks?.length > 0 ? (
                    <ul className={styles.riskList}>
                      {data.risks.map((risk, index) => (
                        <li key={index}>{risk}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className={styles.analysisEmpty}>
                      No key risks are currently available.
                    </p>
                  )}
                </div>

                <div className={styles.analysisSection}>
                  <h3>Key Themes</h3>

                  {data.themes?.length > 0 ? (
                    <div className={styles.themeList}>
                      {data.themes.map((theme, index) => (
                        <span key={index} className={styles.themeTag}>
                          {theme}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className={styles.analysisEmpty}>
                      No key themes are currently available.
                    </p>
                  )}
                </div>

                <div className={styles.analysisSection}>
                  <h3>Current Narrative</h3>

                  <p className={styles.narrativeText}>
                    {data.narrative || "No narrative analysis is currently available."}
                  </p>
                </div>
              </article>
              <CategorySentiment sentiment={categorySentiment} />
            </div>
          </div>
          <BriefAside data={aside} />
        </div>
      </section>
    </AppFrame>
  )
}

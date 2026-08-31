"use client"

import { useEffect, useState } from "react"
import { CategorySentiment } from "../../components/ticker/CategorySentiment"
import { CitationLinks } from "../../components/ticker/CitationLinks"
import { ClarityLayer } from "../../components/ticker/ClarityLayer"
import { PublicDiscussionStatus } from "../../components/ticker/PublicDiscussionStatus"
import { useTickerBrief } from "../../components/ticker/TickerBriefShell"
import { fetchTickerCategorySentiment, fetchTickerPublicDiscussionStatus } from "../../lib/api"
import pageStyles from "../../page.module.css"
import styles from "../../components/research/ResearchSurface.module.css"

// Ticker brief summary tab for "/ticker/[symbol]".
// This route renders only DB-backed ticker overview data so missing data is visible
// during MVP testing.
export default function TickerSummaryRoute() {
  const { error: briefError, isLoading: isBriefLoading, overview: data, symbol } = useTickerBrief()
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState({
    categoryError: "",
    categorySentiment: null,
    discussionError: "",
    discussionStatus: null,
    isLoading: true,
  })

  useEffect(() => {
    let cancelled = false

    setState({
      categoryError: "",
      categorySentiment: null,
      discussionError: "",
      discussionStatus: null,
      isLoading: true,
    })
    Promise.allSettled([
      fetchTickerCategorySentiment(symbol),
      fetchTickerPublicDiscussionStatus(symbol),
    ])
      .then(([categoryResult, discussionResult]) => {
        if (cancelled) return
        setState({
          categoryError: categoryResult.status === "rejected" ? "Saved category signals are unavailable right now." : "",
          categorySentiment: categoryResult.status === "fulfilled" ? categoryResult.value : null,
          discussionError: discussionResult.status === "rejected" ? "Discussion pipeline status is unavailable right now." : "",
          discussionStatus: discussionResult.status === "fulfilled" ? discussionResult.value : null,
          isLoading: false,
        })
      })
    return () => {
      cancelled = true
    }
  }, [attempt, symbol])

  if (isBriefLoading) {
    return (
      <div className={styles.briefContent} aria-live="polite">
        <div className={pageStyles.contentSkeleton}>Loading the latest {symbol} brief…</div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className={styles.briefContent}>
        <div className={styles.statePanel}>
          <h2>Company summary unavailable</h2>
          <p>{briefError || "No saved company summary is available."}</p>
        </div>
      </div>
    )
  }

  const sourceCopy = data.sources_count === 1
    ? "AI-assisted summary based on 1 linked source"
    : data.sources_count > 1
      ? `AI-assisted summary based on ${data.sources_count} linked sources`
      : "AI-assisted summary; linked source material is not available yet"

  return (
    <div className={styles.briefContent}>
      <article className={styles.storyLead}>
        <div className={styles.storyHeading}>
          <h2>Latest research brief</h2>
          <span>Built from the latest stored filing</span>
        </div>
        <div className={styles.storyCopy}>
          <p>{data.story}</p>
          <strong>{sourceCopy}</strong>
          <CitationLinks sources={data.sources} />
        </div>
      </article>
      <ClarityLayer clarity={data.clarity} sources={data.sources} />
      <section className={styles.signalPanel} aria-label="Latest filing sentiment">
        <div>
          <h2>{data.sentiment_label}</h2>
          <p>{data.sentiment_status === "available" ? `The latest analysed filing is classified as ${data.sentiment_label.toLowerCase()}.` : "No analysed filing sentiment is available yet."}</p>
        </div>
        <div className={styles.confidence}>
          <span>Latest model confidence</span>
          <strong>{data.latest_signal_confidence_pct || "N/A"}</strong>
        </div>
      </section>
      {!state.isLoading ? (
        <PublicDiscussionStatus error={state.discussionError} status={state.discussionStatus} />
      ) : null}
      {state.categoryError ? (
        <div className={styles.statePanel} role="alert">
          <p>Category signals could not be loaded. {state.categoryError}</p>
          <button className={styles.secondaryButton} onClick={() => setAttempt((value) => value + 1)} type="button">Try again</button>
        </div>
      ) : state.isLoading ? (
        <div className={pageStyles.contentSkeleton} aria-live="polite">Loading saved category signals…</div>
      ) : (
        <CategorySentiment sentiment={state.categorySentiment} />
      )}
    </div>
  )
}

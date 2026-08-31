"use client"

import { useEffect, useState } from "react"
import { SparkIcon } from "../../components/icons"
import { CategorySentiment } from "../../components/ticker/CategorySentiment"
import { CitationLinks } from "../../components/ticker/CitationLinks"
import { ClarityLayer } from "../../components/ticker/ClarityLayer"
import { PublicDiscussionStatus } from "../../components/ticker/PublicDiscussionStatus"
import { useTickerBrief } from "../../components/ticker/TickerBriefShell"
import { fetchTickerCategorySentiment, fetchTickerPublicDiscussionStatus } from "../../lib/api"
import styles from "../../page.module.css"

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
        <div className={styles.contentSkeleton}>Loading the latest {symbol} brief…</div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className={styles.briefContent}>
        <div className={styles.emptyCard}>
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
      <article className={styles.storyCard}>
        <div className={styles.storyHeading}>
          <h2><SparkIcon /> What&apos;s the story?</h2>
          <span>Latest filing</span>
        </div>
        <p>{data.story}</p>
        <strong>{sourceCopy}</strong>
        <CitationLinks sources={data.sources} />
      </article>
      <ClarityLayer clarity={data.clarity} sources={data.sources} />
      <article className={styles.sentimentCard}>
        <h2>{data.sentiment_label}</h2>
        {data.sentiment_status === "available" ? (
          <>
            <p>The latest analysed filing is classified as {data.sentiment_label.toLowerCase()}.</p>
            <div className={styles.sentimentBar}>
              <span>Latest filing model confidence</span>
              <strong>{data.latest_signal_confidence_pct}</strong>
            </div>
          </>
        ) : (
          <p>No analysed filing sentiment is available yet.</p>
        )}
      </article>
      {!state.isLoading ? (
        <PublicDiscussionStatus error={state.discussionError} status={state.discussionStatus} />
      ) : null}
      {state.categoryError ? (
        <div className={styles.inlineError} role="alert">
          <p>Category signals could not be loaded. {state.categoryError}</p>
          <button className={styles.secondaryButton} onClick={() => setAttempt((value) => value + 1)} type="button">Try again</button>
        </div>
      ) : state.isLoading ? (
        <div className={styles.contentSkeleton} aria-live="polite">Loading saved category signals…</div>
      ) : (
        <CategorySentiment sentiment={state.categorySentiment} />
      )}
    </div>
  )
}

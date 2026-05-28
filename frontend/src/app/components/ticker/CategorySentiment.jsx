import styles from "../../page.module.css"

const CATEGORY_ORDER = [
  ["revenue", "Revenue"],
  ["strategy", "Strategy"],
  ["risk", "Risk"],
  ["dividend", "Dividend"],
  ["organisational", "Organisational"],
  ["user_discussion", "User discussion"],
]

function formatLabel(value) {
  if (!value) {
    return "Neutral"
  }
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase()
}

function percent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return "0%"
  }
  return `${Math.round(number * 100)}%`
}

function categoryRows(sentiment) {
  const categories = sentiment?.categories || {}
  return CATEGORY_ORDER.map(([key, label]) => ({
    key,
    label,
    result: categories[key],
  }))
}

function emptyCategoryMessage(label) {
  if (label === "User discussion") {
    return "No Reddit discussion summary has been stored for this ticker yet."
  }
  return `No ${label.toLowerCase()} evidence in the stored ASX announcements.`
}

function summaryText({ isUnavailable, key, label, result }) {
  if (isUnavailable) {
    return "Sentiment has not been returned by the API yet."
  }
  const summary = result?.summary?.trim()
  if (!summary) {
    return emptyCategoryMessage(label)
  }
  if (summary.length <= 220) {
    return summary
  }
  if (key === "user_discussion") {
    return `${summary.slice(0, 220).trim()}...`
  }
  return "Evidence found in stored ASX announcements."
}

export function CategorySentiment({ sentiment }) {
  const rows = categoryRows(sentiment)
  const isUnavailable = sentiment?.unavailable

  return (
    <article className={styles.categorySentimentCard}>
      <div className={styles.categorySentimentHeader}>
        <div>
          <span>FinBERT category view</span>
          <h2>Sentiment by signal</h2>
        </div>
        <strong>{isUnavailable ? "Unavailable" : sentiment?.model_used || "Starting up"}</strong>
      </div>
      {isUnavailable ? (
        <p className={styles.categorySentimentNotice}>
          Sentiment analysis is waiting for the backend pipeline. Start the API on port 8000, then refresh this ticker.
        </p>
      ) : null}
      <div className={styles.categorySentimentGrid}>
        {rows.map(({ key, label, result }) => {
          const sentimentLabel = result?.sentiment_label || "neutral"
          const confidence = result?.confidence_score || 0
          return (
            <section className={styles.categorySentimentItem} key={key}>
              <div className={styles.categorySentimentTop}>
                <h3>{label}</h3>
                <span className={`${styles.sentimentPill} ${styles[`sentimentPill_${sentimentLabel}`] || ""}`}>
                  {formatLabel(sentimentLabel)}
                </span>
              </div>
              <div className={styles.categorySentimentMeter}>
                <span style={{ width: percent(confidence) }} />
              </div>
              <p>{summaryText({ isUnavailable, key, label, result })}</p>
              <strong>{isUnavailable ? "Waiting for API" : `${percent(confidence)} confidence`}</strong>
            </section>
          )
        })}
      </div>
    </article>
  )
}

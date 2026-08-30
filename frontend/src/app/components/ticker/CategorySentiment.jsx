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
    return "Unavailable"
  }
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase()
}

function percent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return null
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
    return "No public discussion summary has been stored for this ticker yet."
  }
  return `No ${label.toLowerCase()} evidence in the stored ASX announcements.`
}

function summaryText({ key, label, result }) {
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
  const status = sentiment?.status || "unavailable"
  const isUnavailable = status === "unavailable"

  return (
    <article className={styles.categorySentimentCard}>
      <div className={styles.categorySentimentHeader}>
        <h2>Sentiment by signal</h2>
        <strong>{status === "available" ? "Stored analysis" : status === "partial" ? "Partial coverage" : "Unavailable"}</strong>
      </div>
      {isUnavailable ? (
        <p className={styles.categorySentimentNotice}>
          No analysed category signals have been stored for this ticker yet. They will appear after the document analysis pipeline completes.
        </p>
      ) : status === "partial" ? (
        <p className={styles.categorySentimentNotice}>
          Some categories do not yet have analysed source material. Missing signals are shown as unavailable.
        </p>
      ) : null}
      <div className={styles.categorySentimentGrid}>
        {rows.map(({ key, label, result }) => {
          const available = Boolean(result?.available)
          const sentimentLabel = available ? result.sentiment_label : null
          const confidence = available ? percent(result.confidence_score) : null
          return (
            <section className={styles.categorySentimentItem} key={key}>
              <div className={styles.categorySentimentTop}>
                <h3>{label}</h3>
                <span className={`${styles.sentimentPill} ${styles[`sentimentPill_${sentimentLabel || "unavailable"}`] || ""}`}>
                  {formatLabel(sentimentLabel)}
                </span>
              </div>
              <div
                aria-label={`${label} average model confidence`}
                aria-valuemax="100"
                aria-valuemin="0"
                aria-valuenow={available ? Math.round(Number(result.confidence_score) * 100) : undefined}
                className={styles.categorySentimentMeter}
                role={available ? "progressbar" : undefined}
              >
                <span style={{ width: confidence || "0%" }} />
              </div>
              <p>{summaryText({ key, label, result })}</p>
              <strong>{available ? `${confidence} average model confidence` : "No analysed signal"}</strong>
            </section>
          )
        })}
      </div>
    </article>
  )
}

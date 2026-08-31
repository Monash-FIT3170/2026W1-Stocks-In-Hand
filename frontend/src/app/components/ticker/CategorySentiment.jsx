import styles from "../research/ResearchSurface.module.css"

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
  return Math.max(0, Math.min(100, Math.round(number * 100)))
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
    <section className={styles.categoryPanel}>
      <div className={styles.sectionHeader}>
        <div><h2>Signal register</h2><p>Saved analysis grouped by the company topics researchers scan most often.</p></div>
        <strong className={`${styles.statusLabel} ${status === "available" ? styles.statusReady : styles.statusPending}`}>{status === "available" ? "Stored analysis" : status === "partial" ? "Partial coverage" : "Unavailable"}</strong>
      </div>
      {isUnavailable ? (
        <p className={styles.notice}>
          No analysed category signals have been stored for this ticker yet. They will appear after the document analysis pipeline completes.
        </p>
      ) : status === "partial" ? (
        <p className={styles.notice}>
          Some categories do not yet have analysed source material. Missing signals are shown as unavailable.
        </p>
      ) : null}
      <div className={styles.categoryGrid}>
        {rows.map(({ key, label, result }) => {
          const available = Boolean(result?.available)
          const sentimentLabel = available ? result.sentiment_label : null
          const confidence = available ? percent(result.confidence_score) : null
          return (
            <section className={styles.categoryRow} key={key}>
              <h3>{label}</h3>
              <span className={`${styles.sentimentLabel} ${styles[`sentimentLabel_${sentimentLabel || "unavailable"}`] || ""}`}>{formatLabel(sentimentLabel)}</span>
              <p>{summaryText({ key, label, result })}</p>
              <div className={styles.signalScore}>
                <div className={styles.signalScoreLabel}>
                  <strong>{available ? `${confidence}%` : "—"}</strong>
                  <span>{available ? "confidence" : "No signal"}</span>
                </div>
                <div aria-hidden="true" className={styles.signalTrack}>
                  <span className={styles[`signalFill_${sentimentLabel || "unavailable"}`] || ""} style={{ "--signal-width": `${confidence || 0}%` }} />
                </div>
              </div>
            </section>
          )
        })}
      </div>
    </section>
  )
}

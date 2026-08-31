import styles from "../../page.module.css"

const STATUS_LABELS = {
  available: "Analysis ready",
  partial: "Partly analysed",
  pending: "Analysis pending",
  failed: "Analysis failed",
  unavailable: "No posts found",
}

function sourceSummary(sources) {
  const entries = Object.entries(sources || {}).filter(([, count]) => count > 0)
  if (!entries.length) {
    return "No matched Reddit, Bluesky, Mastodon, or blog posts have been collected."
  }
  return entries
    .map(([source, count]) => `${source.charAt(0).toUpperCase()}${source.slice(1)} ${count}`)
    .join(", ")
}

export function PublicDiscussionStatus({ error, status }) {
  if (error) {
    return (
      <article className={styles.discussionStatusCard} role="status">
        <div className={styles.discussionStatusHeader}>
          <div>
            <span>Collection and analysis</span>
            <h2>Public discussion pipeline</h2>
          </div>
          <strong className={`${styles.discussionStatusPill} ${styles.discussionStatusPill_failed}`}>
            Status unavailable
          </strong>
        </div>
        <p className={styles.discussionStatusNotice}>{error}</p>
      </article>
    )
  }

  const counts = status?.counts || {}
  const waiting = (counts.pending || 0) + (counts.queued || 0) + (counts.analyzing || 0)
  const pipelineStatus = status?.status || "unavailable"
  const metrics = [
    ["Collected", counts.total || 0],
    ["Analysed", counts.completed || 0],
    ["Waiting", waiting],
    ["Failed", counts.failed || 0],
  ]

  return (
    <article className={styles.discussionStatusCard}>
      <div className={styles.discussionStatusHeader}>
        <div>
          <span>Collection and analysis</span>
          <h2>Public discussion pipeline</h2>
        </div>
        <strong className={`${styles.discussionStatusPill} ${styles[`discussionStatusPill_${pipelineStatus}`] || ""}`}>
          {STATUS_LABELS[pipelineStatus] || "Status unknown"}
        </strong>
      </div>
      <div className={styles.discussionStatusGrid}>
        {metrics.map(([label, value]) => (
          <div className={styles.discussionStatusMetric} key={label}>
            <strong>{value}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>
      <p className={styles.discussionStatusSources}>{sourceSummary(status?.sources)}</p>
    </article>
  )
}

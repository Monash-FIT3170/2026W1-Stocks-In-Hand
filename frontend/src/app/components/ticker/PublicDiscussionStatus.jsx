import styles from "../research/ResearchSurface.module.css"

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
      <section className={styles.discussionPanel} role="status">
        <div className={styles.sectionHeader}>
          <div>
            <h2>Public discussion pipeline</h2>
            <p>Collection and analysis status across supported public sources.</p>
          </div>
          <strong className={`${styles.statusLabel} ${styles.statusPending}`}>
            Status unavailable
          </strong>
        </div>
        <p className={styles.notice}>{error}</p>
      </section>
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
    <section className={styles.discussionPanel}>
      <div className={styles.sectionHeader}>
        <div>
          <h2>Public discussion pipeline</h2>
          <p>{sourceSummary(status?.sources)}</p>
        </div>
        <strong className={`${styles.statusLabel} ${pipelineStatus === "available" ? styles.statusReady : styles.statusPending}`}>
          {STATUS_LABELS[pipelineStatus] || "Status unknown"}
        </strong>
      </div>
      <div className={styles.discussionMetrics}>
        {metrics.map(([label, value]) => (
          <div className={styles.discussionMetric} key={label}>
            <strong>{value}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

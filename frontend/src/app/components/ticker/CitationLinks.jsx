import styles from "../../page.module.css"

function formatSourceDate(value) {
  if (!value) {
    return ""
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ""
  }

  return new Intl.DateTimeFormat("en-AU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date)
}

function isSafeSourceUrl(value) {
  try {
    const url = new URL(value)
    return url.protocol === "http:" || url.protocol === "https:"
  } catch {
    return false
  }
}

// Compact citation links used across ticker brief sections.
// Each source should include label, title, url, and optional published_at/evidence_text.
export function CitationLinks({ compact = false, sources = [] }) {
  const validSources = sources.filter((source) => isSafeSourceUrl(source?.url))

  if (validSources.length === 0) {
    return null
  }

  return (
    <div
      className={`${styles.citationList} ${compact ? styles.compactCitationList : ""}`}
      aria-label="Citation links"
    >
      {!compact && <span>Sources</span>}
      {validSources.map((source) => {
        const sourceDate = formatSourceDate(source.published_at)
        const title = source.title || source.label || "Source"

        return (
          <a
            href={source.url}
            key={`${source.url}-${title}`}
            rel="noopener noreferrer"
            target="_blank"
            title={source.evidence_text || title}
          >
            <strong>{compact ? "View source" : source.label || "Source"}</strong>
            <em>{sourceDate || (compact ? "Date unavailable" : title)}</em>
          </a>
        )
      })}
    </div>
  )
}

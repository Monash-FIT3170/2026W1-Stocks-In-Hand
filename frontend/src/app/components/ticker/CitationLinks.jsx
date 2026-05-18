import styles from "../../page.module.css"

function formatSourceDate(value) {
  if (!value) {
    return ""
  }

  return new Intl.DateTimeFormat("en-AU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value))
}

// Compact citation links used across ticker brief sections.
// Each source should include label, title, url, and optional published_at/evidence_text.
export function CitationLinks({ sources = [] }) {
  const validSources = sources.filter((source) => source?.url)

  if (validSources.length === 0) {
    return null
  }

  return (
    <div className={styles.citationList} aria-label="Citation links">
      <span>Sources</span>
      {validSources.map((source) => {
        const sourceDate = formatSourceDate(source.published_at)
        const title = source.title || source.label || "Source"

        return (
          <a
            href={source.url}
            key={`${source.url}-${title}`}
            rel="noreferrer"
            target="_blank"
            title={source.evidence_text || title}
          >
            <strong>{source.label || "Source"}</strong>
            <em>{sourceDate || title}</em>
          </a>
        )
      })}
    </div>
  )
}

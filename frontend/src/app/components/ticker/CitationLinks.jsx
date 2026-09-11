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
//
// `title` identifies the exact document (e.g. "FY26 Half Year Results
// Presentation") and is what readers need to tell sources apart, so it is
// always the prominent text. `label` is just the broad source category
// (e.g. "Asx Announcement", "News") and is shown as a secondary tag
// alongside the date rather than in place of the document name.
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
        const documentTitle = source.title || source.label || "Source document"
        const sourceKind = source.label && source.label !== documentTitle ? source.label : null
        const detail = [sourceKind, sourceDate].filter(Boolean).join(" · ")

        return (
          <a
            href={source.url}
            key={`${source.url}-${documentTitle}`}
            rel="noreferrer"
            target="_blank"
            title={source.evidence_text || documentTitle}
          >
            <strong>{documentTitle}</strong>
            <em>{detail || documentTitle}</em>
          </a>
        )
      })}
    </div>
  )
}

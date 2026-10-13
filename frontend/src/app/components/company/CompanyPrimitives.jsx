import styles from "./CompanyWorkspace.module.css"
import { safeSourceUrl, displayDate, publisherLabel } from "./companyFormat"
import { sourceKind } from "../announcements/recordPresentation"
export { safeSourceUrl, displayDate, publisherLabel } from "./companyFormat"

export function ArrowIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M6 18 18 6M6 6h12v12" /></svg> }
export function DocumentIcon() { return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6" /></svg> }

export function SourceLinks({ sources = [], url, label = "Open original source", compact = false, includeDate = true, excerpts = true }) {
  const direct = safeSourceUrl(url)
  const seen = new Set(direct ? [direct] : [])
  const records = (Array.isArray(sources) ? sources : []).filter((source) => {
    if (!source) return false
    const href = safeSourceUrl(source.url)
    if (!href) return true
    if (seen.has(href)) return false
    seen.add(href)
    return true
  })
  return <div className={styles.sources}>
    {direct && <a className={styles.originalLink} href={direct} target="_blank" rel="noopener noreferrer">{label}<ArrowIcon /></a>}
    {records.map((source, index) => {
      const href = safeSourceUrl(source.url)
      return <div className={styles.source} key={`${source.url || source.title || "source"}-${index}`}>
        <DocumentIcon /><div>{href ? <a href={href} title={source.title || source.label} target="_blank" rel="noopener noreferrer">{compact ? publisherLabel(source.label) || "Open original source" : source.title || source.label || "Original source"}<ArrowIcon /></a> : <span>{source.title || source.label || "Source record"} · Link unavailable</span>}
          <small>{[source.source_type ? sourceKind(source.source_type) : null, source.author, includeDate && source.published_at ? displayDate(source.published_at) : null].filter(Boolean).join(" · ")}</small>
          {!compact && excerpts && source.evidence_text && <details className={styles.evidenceExcerpt}><summary>Source excerpt</summary><p>{source.evidence_text}</p></details>}
        </div>
      </div>
    })}
    {!direct && !records.length && <p className={styles.muted}>No original source links are available for this item.</p>}
  </div>
}

export function ResourceState({ resource, name, children }) {
  if (resource.error) return <div className={styles.state} role="alert"><h3>{name} could not be loaded</h3><p>{resource.error}</p><button className={styles.button} onClick={resource.retry} type="button">Retry {name.toLowerCase()}</button></div>
  if (resource.isLoading) return <div className={styles.loading} role="status" aria-label={`Loading ${name.toLowerCase()}`}><span /><span /><span /><p>Loading {name.toLowerCase()}…</p></div>
  return children
}

export function EmptyState({ title, children }) { return <div className={styles.state}><h3>{title}</h3><p>{children}</p></div> }
export function sentimentClass(label) {
  const value = String(label || "").toLowerCase()
  if (value.includes("negative")) return styles.negative
  if (value.includes("positive")) return styles.positive
  return styles.neutral
}

import Link from "next/link"
import styles from "../research/ResearchSurface.module.css"
import { CitationLinks } from "../ticker/CitationLinks"

// Shared announcement summary card.
// Used by both the global market feed and the ticker news tab. Keep the data
// shape simple here: each card expects an item with ticker, tag, time, title, about,
// changed, matters, and url fields.
export function AnnouncementCard({ item }) {
  const filingUrl = item.url || null
  const sourceLabel = item.source_label || "View original source"

  return (
    <article className={styles.announcementCard}>
      <div className={styles.sourceRail}>
        <span className={styles.sourceIndex} aria-hidden="true" />
        <span className={styles.tickerMark}>{item.ticker}</span>
        <span className={styles.sourceKind}>{item.tag || item.source_type || "Source record"}</span>
      </div>
      <div className={styles.announcementBody}>
        <div className={styles.announcementMeta}>
          <span>{item.source_name || item.tag || "Market source"}</span><b aria-hidden="true" /><time>{item.time}</time>
        </div>
        <h2>{item.title}</h2>
        <div className={styles.announcementLead}>
          <div><h3>What changed</h3><p>{item.changed}</p></div>
          <div className={styles.researchAngle}><h3>Research angle</h3><p>{item.matters}</p></div>
        </div>
        <div className={styles.announcementContext}><h3>Context</h3><p>{item.about}</p></div>
        <footer className={styles.announcementFooter}>
          <div className={styles.announcementActions}>
            <Link href={`/ticker/${item.ticker}/news`}>Open {item.ticker} research</Link>
            {filingUrl ? <a href={filingUrl} rel="noreferrer" target="_blank">{sourceLabel}</a> : null}
          </div>
          <CitationLinks sources={item.sources} />
        </footer>
      </div>
    </article>
  )
}

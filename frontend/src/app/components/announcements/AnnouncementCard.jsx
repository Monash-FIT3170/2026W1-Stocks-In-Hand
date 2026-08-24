import Link from "next/link"
import styles from "../../page.module.css"
import { CitationLinks } from "../ticker/CitationLinks"

// Shared announcement summary card.
// Used by both the global announcements feed and the ticker news tab. Keep the data
// shape simple here: each card expects an item with ticker, tag, time, title, about,
// changed, matters, and url fields.
export function AnnouncementCard({ item }) {
  const filingUrl = item.url || null
  const sourceLabel = item.source_label || "View original ASX filing"

  return (
    <article className={styles.announcementCard}>
      <div className={styles.cardTopLine}>
        <span className={styles.tickerPill}>{item.ticker}</span>
        <span className={styles.redPill}>{item.tag}</span>
        <span>{item.time}</span>
      </div>
      <h2>{item.title}</h2>
      <div className={styles.explainGrid}>
        <div><span>What it&apos;s about</span><p>{item.about}</p></div>
        <div><span>What changed</span><p>{item.changed}</p></div>
        <div><span>Why it matters</span><p>{item.matters}</p></div>
      </div>
      <div className={styles.cardActions}>
        <Link href={`/ticker/${item.ticker}/news`}>View {item.ticker} news feed</Link>
        {filingUrl ? <a href={filingUrl} rel="noreferrer" target="_blank">{sourceLabel}</a> : null}
      </div>
      <CitationLinks sources={item.sources} />
    </article>
  )
}

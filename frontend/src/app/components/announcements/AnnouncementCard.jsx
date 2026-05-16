import Link from "next/link"
import styles from "../../page.module.css"
import { BookmarkIcon } from "../icons"

// Shared announcement summary card.
// Used by both the global announcements feed and the ticker news tab. Keep the data
// shape simple here: each card expects an item with ticker, tag, time, title, about,
// changed, matters, and url fields.
export function AnnouncementCard({ item }) {
  const filingUrl = item.url || "#"

  return (
    <article className={styles.announcementCard}>
      <div className={styles.cardTopLine}>
        <span className={styles.tickerPill}>{item.ticker}</span>
        <span className={styles.redPill}>{item.tag}</span>
        <span>{item.time}</span>
        <BookmarkIcon />
      </div>
      <h2>{item.title}</h2>
      <div className={styles.explainGrid}>
        <div><span>What it&apos;s about</span><p>{item.about}</p></div>
        <div><span>What changed</span><p>{item.changed}</p></div>
        <div><span>Why it matters</span><p>{item.matters}</p></div>
      </div>
      <div className={styles.cardActions}>
        <Link href={`/ticker/${item.ticker}/news`}>Read full summary</Link>
        <a href={filingUrl}>View original ASX filing</a>
      </div>
    </article>
  )
}

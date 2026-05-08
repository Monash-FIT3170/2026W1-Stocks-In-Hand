import Link from "next/link"
import styles from "../../page.module.css"
import { BookmarkIcon } from "../icons"

export function AnnouncementCard({ item }) {
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
        <Link href="/ticker/BHP/news">Read full summary</Link>
        <a href="#">View original ASX filing</a>
      </div>
    </article>
  )
}

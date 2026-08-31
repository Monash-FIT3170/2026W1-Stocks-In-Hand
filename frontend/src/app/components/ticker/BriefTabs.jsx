import Link from "next/link"
import styles from "../../page.module.css"

export function BriefTabs({ active, symbol }) {
  const ticker = symbol ? symbol.toUpperCase() : "BHP"

  return (
    <nav aria-label={`${ticker} brief sections`} className={styles.tabBar}>
      <Link aria-current={active === "summary" ? "page" : undefined} className={active === "summary" ? styles.activeTab : styles.tabButton} href={`/ticker/${ticker}`}>Summary</Link>
      <Link aria-current={active === "news" ? "page" : undefined} className={active === "news" ? styles.activeTab : styles.tabButton} href={`/ticker/${ticker}/news`}>News & Announcements</Link>
      <Link aria-current={active === "deep" ? "page" : undefined} className={active === "deep" ? styles.activeTab : styles.tabButton} href={`/ticker/${ticker}/deep-dive`}>Deep Dive</Link>
    </nav>
  )
}

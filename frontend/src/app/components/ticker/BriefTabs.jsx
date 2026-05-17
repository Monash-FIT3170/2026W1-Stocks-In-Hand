import Link from "next/link"
import styles from "../../page.module.css"

export function BriefTabs({ active, symbol }) {
  const ticker = symbol ? symbol.toUpperCase() : "BHP"
  
  return (
    <div className={styles.tabBar}>
      <Link className={active === "summary" ? styles.activeTab : styles.tabButton} href={`/ticker/${ticker}`}>Summary</Link>
      <Link className={active === "news" ? styles.activeTab : styles.tabButton} href={`/ticker/${ticker}/news`}>News & Announcements</Link>
      <Link className={active === "deep" ? styles.activeTab : styles.tabButton} href={`/ticker/${ticker}/deep-dive`}>Deep Dive</Link>
    </div>
  )
}
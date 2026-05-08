import Link from "next/link"
import styles from "../../page.module.css"

export function BriefTabs({ active }) {
  return (
    <div className={styles.tabBar}>
      <Link className={active === "summary" ? styles.activeTab : styles.tabButton} href="/ticker/BHP">Summary</Link>
      <Link className={active === "news" ? styles.activeTab : styles.tabButton} href="/ticker/BHP/news">News & Announcements</Link>
      <Link className={active === "deep" ? styles.activeTab : styles.tabButton} href="/ticker/BHP/deep-dive">Deep Dive</Link>
    </div>
  )
}

import Link from "next/link"
import styles from "../../page.module.css"

// Tab navigation for the ticker brief pages.
// The active prop is controlled by each route file. Hrefs are hard-coded to BHP for
// the prototype; once route params are used, pass the current symbol into this component
// and build the links from that symbol instead.
export function BriefTabs({ active }) {
  return (
    <div className={styles.tabBar}>
      <Link className={active === "summary" ? styles.activeTab : styles.tabButton} href="/ticker/BHP">Summary</Link>
      <Link className={active === "news" ? styles.activeTab : styles.tabButton} href="/ticker/BHP/news">News & Announcements</Link>
      <Link className={active === "deep" ? styles.activeTab : styles.tabButton} href="/ticker/BHP/deep-dive">Deep Dive</Link>
    </div>
  )
}

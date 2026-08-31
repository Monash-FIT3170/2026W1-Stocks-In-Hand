import Link from "next/link"
import styles from "../research/ResearchSurface.module.css"

export function BriefTabs({ active, symbol }) {
  const ticker = symbol ? symbol.toUpperCase() : "BHP"

  return (
    <nav aria-label={`${ticker} brief sections`} className={styles.tabBar}>
      <Link aria-current={active === "summary" ? "page" : undefined} className={active === "summary" ? styles.activeTabLink : styles.tabLink} href={`/ticker/${ticker}`}>Research summary</Link>
      <Link aria-current={active === "news" ? "page" : undefined} className={active === "news" ? styles.activeTabLink : styles.tabLink} href={`/ticker/${ticker}/news`}>Source records</Link>
      <Link aria-current={active === "deep" ? "page" : undefined} className={active === "deep" ? styles.activeTabLink : styles.tabLink} href={`/ticker/${ticker}/deep-dive`}>Deep dive</Link>
    </nav>
  )
}

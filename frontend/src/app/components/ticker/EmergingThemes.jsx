import { themes } from "../../mock/ticker"
import styles from "../../page.module.css"

// Reusable themes panel shown on announcements and ticker brief pages.
// The list currently comes from mock/ticker.js and can later be fed by extracted
// themes from filings/news without changing the panel layout.
export function EmergingThemes() {
  return (
    <section className={styles.sideCard}>
      <h2>Emerging themes</h2>
      <ul>{themes.map((theme) => <li key={theme}>{theme}</li>)}</ul>
    </section>
  )
}

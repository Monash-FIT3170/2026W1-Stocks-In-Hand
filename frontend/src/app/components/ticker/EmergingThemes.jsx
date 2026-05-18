import { themes } from "../../mock/ticker"
import styles from "../../page.module.css"

export function EmergingThemes() {
  return (
    <section className={styles.sideCard}>
      <div className={styles.sideCardTitle}>
        <h2>Emerging themes</h2>
        <span>Mocked</span>
      </div>
      <ul>{themes.map((theme) => <li key={theme}>{theme}</li>)}</ul>
    </section>
  )
}

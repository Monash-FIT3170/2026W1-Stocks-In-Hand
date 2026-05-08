import { themes } from "../../mock/ticker"
import styles from "../../page.module.css"

export function EmergingThemes() {
  return (
    <section className={styles.sideCard}>
      <h2>Emerging themes</h2>
      <ul>{themes.map((theme) => <li key={theme}>{theme}</li>)}</ul>
    </section>
  )
}

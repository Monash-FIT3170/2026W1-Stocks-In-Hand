import styles from "../../page.module.css"

export function EmergingThemes({ themes = [] }) {
  return (
    <section className={styles.sideCard}>
      <div className={styles.sideCardTitle}>
        <h2>Emerging themes</h2>
      </div>
      {themes.length > 0
        ? <ul>{themes.map((theme) => <li key={theme}>{theme}</li>)}</ul>
        : <p className={styles.claim}>No themes derived from stored filings yet.</p>}
    </section>
  )
}

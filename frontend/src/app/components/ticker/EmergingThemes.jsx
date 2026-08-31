import styles from "../research/ResearchSurface.module.css"

export function EmergingThemes({ themes = [] }) {
  return (
    <section className={styles.asideSection}>
      <h2>Emerging themes</h2>
      {themes.length > 0
        ? <ul className={styles.themeList}>{themes.map((theme) => <li key={theme}>{theme}</li>)}</ul>
        : <p className={styles.asideEmpty}>No themes derived from stored filings yet.</p>}
    </section>
  )
}

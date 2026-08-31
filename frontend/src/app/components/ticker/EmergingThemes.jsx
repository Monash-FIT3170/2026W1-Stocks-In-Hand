import styles from "../../page.module.css"

function cleanThemes(themes) {
  if (!Array.isArray(themes)) {
    return []
  }

  const seen = new Set()

  return themes
    .map((theme) => String(theme || "").trim())
    .filter((theme) => {
      if (!theme) {
        return false
      }

      const key = theme.toLowerCase()

      if (seen.has(key)) {
        return false
      }

      seen.add(key)
      return true
    })
    .slice(0, 5)
}

export function EmergingThemes({ themes = [] }) {
  const cleanedThemes = cleanThemes(themes)

  return (
    <section className={styles.sideCard}>
      <div className={styles.sideCardTitle}>
        <h2>Emerging themes</h2>
      </div>

      {cleanedThemes.length > 0 ? (
        <ul>
          {cleanedThemes.map((theme) => (
            <li key={theme}>{theme}</li>
          ))}
        </ul>
      ) : (
        <p className={styles.claim}>
          No recurring themes have been identified from stored filings yet.
        </p>
      )}
    </section>
  )
}
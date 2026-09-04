import styles from "../research/ResearchSurface.module.css"

export function KeyNumbers({ items = [] }) {
  return (
    <section className={styles.asideSection}>
      <h2>Key numbers</h2>
      <div className={styles.numberList}>
      {items.length > 0
        ? items.map((item) => (
            <div className={styles.numberRow} key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>
          ))
        : <p className={styles.asideEmpty}>No key numbers available yet.</p>}
      </div>
    </section>
  )
}

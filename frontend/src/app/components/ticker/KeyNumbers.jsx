import styles from "../../page.module.css"
import { ChartIcon } from "../icons"

export function KeyNumbers({ items = [] }) {
  return (
    <section className={styles.sideCard}>
      <div className={styles.sideCardTitle}>
        <h2><ChartIcon /> Key numbers</h2>
      </div>
      {items.length > 0
        ? items.map((item) => (
            <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>
          ))
        : <p className={styles.claim}>No key numbers available yet.</p>}
    </section>
  )
}

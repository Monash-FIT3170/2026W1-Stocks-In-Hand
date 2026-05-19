import styles from "../../page.module.css"

// Tiny reusable stat card used by the ticker header.
// Keep it generic: label/value only, no stock-specific assumptions.
export function MetricCard({ label, value }) {
  return <div className={styles.metricCard}><span>{label}</span><strong>{value}</strong></div>
}

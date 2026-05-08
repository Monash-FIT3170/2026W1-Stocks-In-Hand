import styles from "../../page.module.css"

export function MetricCard({ label, value }) {
  return <div className={styles.metricCard}><span>{label}</span><strong>{value}</strong></div>
}

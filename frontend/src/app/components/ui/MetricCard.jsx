import styles from "../research/ResearchSurface.module.css"

// Tiny reusable stat card used by the ticker header.
// Keep it generic: label/value only, no stock-specific assumptions.
export function MetricCard({ label, value }) {
  return <div className={styles.metric}><span>{label}</span><strong>{value || "N/A"}</strong></div>
}

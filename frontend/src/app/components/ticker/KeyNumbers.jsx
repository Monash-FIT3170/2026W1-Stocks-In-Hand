import styles from "../../page.module.css"
import { ChartIcon } from "../icons"

// Ticker sidebar numbers.
// These values are static placeholders; once the company profile endpoint exists,
// pass revenue/report date as props or replace this with a data-aware container.
export function KeyNumbers() {
  return (
    <section className={styles.sideCard}>
      <h2><ChartIcon /> Key numbers</h2>
      <div><span>Revenue</span><strong>$14.2B</strong></div>
      <div><span>Next report</span><strong>Aug 2025</strong></div>
    </section>
  )
}

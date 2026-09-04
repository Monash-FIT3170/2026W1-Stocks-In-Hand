import Link from "next/link"
import styles from "../page.module.css"

export const metadata = { title: "About | StonksInHand" }

export default function AboutRoute() {
  return (
    <section className={`${styles.contentPage} ${styles.informationPage}`}>
      <h1>About StonksInHand</h1>
      <p>StonksInHand helps people scan recent ASX company information without replacing the underlying source documents.</p>
      <section>
        <h2>How briefs are prepared</h2>
        <p>Automated workers collect supported announcements and publisher records, extract their text, and prepare AI-assisted summaries and sentiment signals. Where a source URL is available, the interface links back to it so you can verify the context.</p>
      </section>
      <section>
        <h2>What it is not</h2>
        <p>The service is an information and research aid. It does not provide personal financial advice or guarantee that a summary is complete, current, or suitable for an investment decision.</p>
      </section>
      <Link className={styles.secondaryButton} href="/data-sources">Review the data sources</Link>
    </section>
  )
}

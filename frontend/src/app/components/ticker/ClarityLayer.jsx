import styles from "../research/ResearchSurface.module.css"
import { CitationLinks } from "./CitationLinks"

function ClaimList({ emptyMessage, items }) {
  if (items.length === 0) {
    return <p className={styles.claimEmpty}>{emptyMessage}</p>
  }

  return (
    <ul className={styles.claimList}>
      {items.map((item) => <li key={item}>{item}</li>)}
    </ul>
  )
}

export function ClarityLayer({ clarity = {}, sources = [] }) {
  const confirmedFacts = clarity.confirmed_facts || []
  const speculation = clarity.speculation || []

  if (!clarity.is_classified) {
    return (
      <section className={styles.clarityPanel} aria-label="Fact and speculation clarity">
        <div className={styles.sectionHeader}>
          <div>
            <h2>Verification status</h2>
            <p>The latest summary has not yet been separated into supported facts and forward-looking interpretation.</p>
          </div>
          <strong className={`${styles.statusLabel} ${styles.statusPending}`}>Not classified</strong>
        </div>
        <p className={styles.notice}>
          This announcement has not been classified into confirmed facts and
          speculation yet. Treat the summary as AI-generated analysis.
        </p>
      </section>
    )
  }

  return (
    <section className={styles.clarityPanel} aria-label="Fact and speculation clarity">
      <div className={styles.sectionHeader}>
        <div>
          <h2>Verification map</h2>
          <p>Claims are separated by whether they describe supported facts or forward-looking interpretation.</p>
        </div>
        <strong className={`${styles.statusLabel} ${styles.statusReady}`}>Classified</strong>
      </div>
      <div className={styles.clarityGrid}>
        <section className={styles.clarityGroup}>
          <h3>Confirmed facts</h3>
          <ClaimList
            emptyMessage="No confirmed factual claims were identified."
            items={confirmedFacts}
          />
          <CitationLinks sources={sources} />
        </section>

        <section className={styles.clarityGroup}>
          <h3>Forward-looking interpretation</h3>
          <ClaimList
            emptyMessage="No speculative or forward-looking claims were identified."
            items={speculation}
          />
        </section>
      </div>
    </section>
  )
}

import { BadgeIcon, SparkIcon } from "../icons"
import styles from "../../page.module.css"
import { CitationLinks } from "./CitationLinks"

function ClaimList({ emptyMessage, items }) {
  if (items.length === 0) {
    return <p className={styles.clarityEmpty}>{emptyMessage}</p>
  }

  return (
    <ul className={styles.clarityClaims}>
      {items.map((item) => <li key={item}>{item}</li>)}
    </ul>
  )
}

export function ClarityLayer({ clarity = {}, sources = [] }) {
  const confirmedFacts = clarity.confirmed_facts || []
  const speculation = clarity.speculation || []

  if (!clarity.is_classified) {
    return (
      <section className={styles.clarityCard} aria-label="Fact and speculation clarity">
        <div className={styles.clarityHeader}>
          <div>
            <span>Clarity layer</span>
            <h2>Fact check pending</h2>
          </div>
          <strong className={styles.clarityPending}>Not classified</strong>
        </div>
        <p className={styles.clarityNotice}>
          This announcement has not been classified into confirmed facts and
          speculation yet. Treat the summary as AI-generated analysis.
        </p>
      </section>
    )
  }

  return (
    <section className={styles.clarityCard} aria-label="Fact and speculation clarity">
      <div className={styles.clarityHeader}>
        <div>
          <span>Clarity layer</span>
          <h2>What&apos;s verified?</h2>
        </div>
        <strong className={styles.clarityReady}>Classified</strong>
      </div>

      <p className={styles.clarityIntro}>
        Claims are separated by whether they describe supported facts or
        forward-looking interpretation.
      </p>

      <div className={styles.clarityGrid}>
        <section className={`${styles.clarityGroup} ${styles.clarityConfirmed}`}>
          <div className={styles.clarityGroupTitle}>
            <BadgeIcon />
            <div>
              <h3>Confirmed facts</h3>
              <p>Directly supported by the official announcement.</p>
            </div>
          </div>
          <ClaimList
            emptyMessage="No confirmed factual claims were identified."
            items={confirmedFacts}
          />
          <CitationLinks sources={sources} />
        </section>

        <section className={`${styles.clarityGroup} ${styles.claritySpeculation}`}>
          <div className={styles.clarityGroupTitle}>
            <SparkIcon />
            <div>
              <h3>Speculation</h3>
              <p>Forecasts, expectations, opinions, and possible impacts.</p>
            </div>
          </div>
          <ClaimList
            emptyMessage="No speculative or forward-looking claims were identified."
            items={speculation}
          />
        </section>
      </div>
    </section>
  )
}

import { BadgeIcon, SparkIcon } from "../icons"
import styles from "../../page.module.css"
import { CitationLinks } from "./CitationLinks"

function ClaimList({ emptyMessage, items, kind, traceableClaims }) {
  if (items.length === 0) {
    return <p className={styles.clarityEmpty}>{emptyMessage}</p>
  }

  const hasTraceability = Array.isArray(traceableClaims)

  return (
    <ul className={styles.clarityClaims}>
      {items.map((item) => {
        const traceableClaim = hasTraceability
          ? traceableClaims.find((claim) => claim?.kind === kind && claim?.text === item)
          : null
        const source = traceableClaim?.source

        return (
          <li key={item}>
            <span className={styles.claimText}>{item}</span>
            {hasTraceability && source && (
              <>
                {source.evidence_text && (
                  <blockquote className={styles.claimEvidence}>
                    <strong>Exact passage</strong>
                    {source.evidence_text}
                  </blockquote>
                )}
                <CitationLinks compact sources={[source]} />
              </>
            )}
            {hasTraceability && !source && (
              <span className={styles.claimSourceUnavailable}>Source unavailable</span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

export function ClarityLayer({ clarity = {}, sources = [] }) {
  const confirmedFacts = clarity.confirmed_facts || []
  const speculation = clarity.speculation || []
  const traceableClaims = clarity.traceable_claims
  const hasTraceability = Array.isArray(traceableClaims)

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
            kind="confirmed_fact"
            traceableClaims={traceableClaims}
          />
          {!hasTraceability && <CitationLinks sources={sources} />}
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
            kind="speculation"
            traceableClaims={traceableClaims}
          />
        </section>
      </div>
    </section>
  )
}

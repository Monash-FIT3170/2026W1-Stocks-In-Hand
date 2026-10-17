import { EmptyState, SourceLinks, safeSourceUrl } from "./CompanyPrimitives"
import styles from "./CompanyWorkspace.module.css"

function ClaimList({ items = [], kind, traceableClaims, emptyMessage }) {
  const hasTraceability = Array.isArray(traceableClaims)
  if (!items.length) return <p>{emptyMessage}</p>
  return <ul className={styles.clarityClaims}>{items.map((text) => {
    const source = hasTraceability ? traceableClaims.find((claim) => claim?.kind === kind && claim?.text === text)?.source : null
    const hasSource = safeSourceUrl(source?.url)
    const hasDate = source?.published_at && !Number.isNaN(new Date(source.published_at).getTime())
    return <li key={text}><span>{text}</span>{hasTraceability && (hasSource ? <>
      {source.evidence_text ? <blockquote className={styles.claimEvidence}><strong>Exact passage</strong>{source.evidence_text}</blockquote> : <p className={styles.muted}>Exact passage unavailable</p>}
      <SourceLinks sources={[source]} compact includeDate={Boolean(hasDate)} />
      {!hasDate && <small className={styles.muted}>Date unavailable</small>}
    </> : <p className={styles.muted}>Source unavailable</p>)}</li>
  })}</ul>
}

export function ClarityLayer({ clarity = {}, sources = [] }) {
  return <section className={`${styles.section} ${styles.factsSection}`} id="research-clarity">
    <div className={styles.sectionHeading}><h2>Facts &amp; interpretation</h2><p>AI-assisted classification of the stored research.</p></div>
    {clarity.is_classified ? <>
      <div className={styles.clarityColumns}>
        <div><h3>Confirmed facts</h3><ClaimList items={clarity.confirmed_facts} kind="confirmed_fact" traceableClaims={clarity.traceable_claims} emptyMessage="No confirmed facts were returned." /></div>
        <div><h3>Interpretation &amp; speculation</h3><ClaimList items={clarity.speculation} kind="speculation" traceableClaims={clarity.traceable_claims} emptyMessage="No interpretation was returned." /></div>
      </div>
      {!Array.isArray(clarity.traceable_claims) && sources.length > 0 && <SourceLinks sources={sources} />}
    </> : <EmptyState title="This research has not been classified">The stored text has not yet been separated into confirmed facts and interpretation. Check its original sources before relying on a claim.</EmptyState>}
  </section>
}

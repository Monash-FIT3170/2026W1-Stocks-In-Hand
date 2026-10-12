import { safeSourceUrl } from "../../lib/traceability"
import styles from "../../page.module.css"

export function ClaimEvidence({ claim, source }) {
  const original = claim?.source || source
  const url = safeSourceUrl(original?.url)
  const passages = Array.isArray(claim?.evidence)
    ? claim.evidence.filter((item) => typeof item?.quote === "string" && item.quote.trim())
    : []
  const hasQuotation = claim?.status === "quoted" && url && passages.length > 0

  if (!hasQuotation) {
    return (
      <div className={styles.claimEvidenceMissing}>
        <span>{url ? "No source quotation available for this claim." : "Original source link unavailable."}</span>
        {url ? <a href={url} rel="noopener noreferrer" target="_blank">Open original source</a> : null}
      </div>
    )
  }

  return (
    <details className={styles.claimEvidence}>
      <summary>View source quotation <span>({passages.length})</span></summary>
      <div className={styles.claimEvidenceBody}>
        {passages.map((passage, index) => (
          <blockquote key={`${passage.start_char}-${index}`}>
            <p>{passage.quote}</p>
          </blockquote>
        ))}
        <a href={url} rel="noopener noreferrer" target="_blank">
          Open original source{original?.title ? `: ${original.title}` : ""}
        </a>
        <p className={styles.claimEvidenceNote}>
          Quotation matched to stored source text. Review the original for context.
        </p>
      </div>
    </details>
  )
}

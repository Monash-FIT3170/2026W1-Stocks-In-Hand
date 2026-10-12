import { ClaimEvidence } from "./ClaimEvidence"
import styles from "../../page.module.css"

export function ClaimTraceList({ claims = [] }) {
  if (claims.length === 0) return null
  return (
    <details className={styles.timelineClaims}>
      <summary>Trace individual claims</summary>
      <ul>
        {claims.map((claim) => (
          <li key={claim.id}>
            <p>{claim.text}</p>
            <ClaimEvidence claim={claim} />
          </li>
        ))}
      </ul>
    </details>
  )
}

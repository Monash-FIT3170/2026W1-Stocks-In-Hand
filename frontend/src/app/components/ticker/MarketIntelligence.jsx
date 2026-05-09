import { marketClaims } from "../../mock/ticker"
import styles from "../../page.module.css"

// Confirmed/rumoured market intelligence panel.
// Keep wording and grouping in mock/ticker.js for now. Later this component can render
// sourced claims, confidence levels, and links without changing the parent pages.
export function MarketIntelligence() {
  return (
    <section className={styles.sideCardWhite}>
      <h2>Market Intelligence</h2>
      <h3>Confirmed</h3>
      {marketClaims.confirmed.map((claim) => <p className={styles.claim} key={claim}>{claim}</p>)}
      <h3 className={styles.rumoured}>Rumoured</h3>
      {marketClaims.rumoured.map((claim) => <p className={styles.claim} key={claim}>{claim}</p>)}
    </section>
  )
}

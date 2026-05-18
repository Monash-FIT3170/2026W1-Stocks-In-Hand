import { marketClaims } from "../../mock/ticker"
import styles from "../../page.module.css"

export function MarketIntelligence() {
  return (
    <section className={styles.sideCardWhite}>
      <div className={styles.sideCardTitle}>
        <h2>Market Intelligence</h2>
        <span>Mocked</span>
      </div>
      <h3>Confirmed</h3>
      {marketClaims.confirmed.map((claim) => <p className={styles.claim} key={claim}>{claim}</p>)}
      <h3 className={styles.rumoured}>Rumoured</h3>
      {marketClaims.rumoured.map((claim) => <p className={styles.claim} key={claim}>{claim}</p>)}
    </section>
  )
}

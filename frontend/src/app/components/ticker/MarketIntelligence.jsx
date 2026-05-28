import styles from "../../page.module.css"

export function MarketIntelligence({ intelligence = {} }) {
  const confirmed = intelligence.confirmed || []
  const rumoured = intelligence.rumoured || []

  return (
    <section className={styles.sideCardWhite}>
      <div className={styles.sideCardTitle}>
        <h2>Market Intelligence</h2>
      </div>
      <h3>Confirmed</h3>
      {confirmed.length > 0
        ? confirmed.map((claim) => <p className={styles.claim} key={claim}>{claim}</p>)
        : <p className={styles.claim}>No confirmed claims linked to stored sources yet.</p>}
      <h3 className={styles.rumoured}>Rumoured</h3>
      {rumoured.length > 0
        ? rumoured.map((claim) => <p className={styles.claim} key={claim}>{claim}</p>)
        : <p className={styles.claim}>No rumoured claims in the database.</p>}
    </section>
  )
}

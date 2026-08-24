import styles from "../page.module.css"

export const metadata = { title: "Data sources | StonksInHand" }

const sources = [
  ["ASX and issuer filings", "Company announcements and related documents collected from supported issuer or ASX-facing sources."],
  ["Publisher news", "Stored publisher records supplied through the configured news integration, with the original publisher URL retained when available."],
  ["Investor discussion", "Public discussion records from configured communities such as Reddit. Discussion is clearly separated from official company material."],
  ["Market quotes", "Current and previous-close quote fields requested from Yahoo Finance. Quotes can be delayed or temporarily unavailable."],
]

export default function DataSourcesRoute() {
  return (
    <section className={`${styles.contentPage} ${styles.informationPage}`}>
      <h1>Data sources</h1>
      <p>Each brief can combine different source types. A source link is shown whenever the stored record includes one.</p>
      <div className={styles.sourceDirectory}>
        {sources.map(([title, description]) => (
          <section key={title}>
            <h2>{title}</h2>
            <p>{description}</p>
          </section>
        ))}
      </div>
      <p className={styles.informationNotice}>Always open the original filing or publisher page before relying on a material claim. A missing link means the application has not stored a verifiable source URL for that record.</p>
    </section>
  )
}

import styles from "../page.module.css"

export const metadata = { title: "Terms | StonksInHand" }

export default function TermsRoute() {
  return (
    <section className={`${styles.contentPage} ${styles.informationPage}`}>
      <h1>Terms of use</h1>
      <p>By using StonksInHand, you agree to use the service as a research aid and to verify material information with the original issuer or publisher.</p>
      <section>
        <h2>No financial advice</h2>
        <p>Content is general information only. It does not consider your objectives, financial situation, or needs and is not a recommendation to buy, sell, or hold a security.</p>
      </section>
      <section>
        <h2>AI-assisted content</h2>
        <p>Summaries and classifications may be incomplete or incorrect. Source availability, third-party outages, and processing delays can affect what appears in a brief.</p>
      </section>
      <section>
        <h2>Account use</h2>
        <p>You are responsible for activity under your account and for keeping your sign-in details secure. Do not attempt to disrupt the service or access another person&apos;s data.</p>
      </section>
      <section>
        <h2>Availability</h2>
        <p>The service is provided on an as-available basis and may change as supported data sources and analysis pipelines evolve.</p>
      </section>
    </section>
  )
}

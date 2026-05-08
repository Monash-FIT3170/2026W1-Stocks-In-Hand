import Link from "next/link"
import { AuthField } from "../components/auth/AuthField"
import { AppFrame } from "../components/layout/AppFrame"
import styles from "../page.module.css"

export default function SignUpRoute() {
  return (
    <AppFrame>
      <section className={styles.authPage}>
        <form className={styles.authCard}>
          <h1>Start your investing journey</h1>
          <p>Join thousands of retail investors getting clear, plain-English ASX insights.</p>
          <AuthField label="Full name" placeholder="E.g. Jane Doe" />
          <AuthField label="Email address" placeholder="jane@example.com" />
          <AuthField label="Password" placeholder="At least 8 characters" password />
          <Link className={styles.authSubmit} href="/watchlist">Create account</Link>
          <span className={styles.authSwap}>Already have an account?<Link href="/sign-in">Sign in</Link></span>
        </form>
        <div className={styles.securityNote}>Institutional-grade security for your ASX data</div>
      </section>
    </AppFrame>
  )
}

import Link from "next/link"
import { AuthField } from "../components/auth/AuthField"
import { AppFrame } from "../components/layout/AppFrame"
import styles from "../page.module.css"

export default function SignInRoute() {
  return (
    <AppFrame>
      <section className={styles.authPage}>
        <form className={styles.authCard}>
          <h1>Welcome back</h1>
          <p>Access your ASX portfolio and AI wealth insights.</p>
          <AuthField label="Email address" placeholder="name@example.com" />
          <AuthField label="Password" placeholder="Enter your password" password />
          <Link className={styles.authSubmit} href="/watchlist">Sign In</Link>
          <span className={styles.authSwap}>Don&apos;t have an account?<Link href="/sign-up">Sign up</Link></span>
        </form>
      </section>
    </AppFrame>
  )
}

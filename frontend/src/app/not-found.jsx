import Link from "next/link"
import styles from "./page.module.css"

export const metadata = { title: "Page not found | StonksInHand" }

export default function NotFound() {
  return (
    <section className={styles.notFoundPage}>
      <h1>404 — That page isn&apos;t in this brief</h1>
      <p>The address may be incorrect, or the ticker has not been included in the current frontend release.</p>
      <div>
        <Link className={styles.primaryAction} href="/">Return home</Link>
        <Link className={styles.secondaryButton} href="/search">Search companies</Link>
      </div>
    </section>
  )
}

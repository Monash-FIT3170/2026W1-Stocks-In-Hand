import Link from "next/link"
import styles from "./AppFrame.module.css"

export function AppFrame({
  active,
  signedIn = false,
  children,
}) {
  return (
    <main className={styles.appShell}>
      <header className={styles.topNav}>
        <div className={styles.navInner}>
          <Link className={styles.brandButton} href="/">StonksInHand</Link>
          <nav className={styles.navLinks} aria-label="Primary">
            <Link className={active === "home" ? styles.activeNavLink : styles.navLink} href="/">Home</Link>
            <Link className={active === "announcements" ? styles.activeNavLink : styles.navLink} href="/announcements">Announcements</Link>
            {signedIn && <Link className={active === "watchlist" ? styles.activeNavLink : styles.navLink} href="/watchlist">My Watchlist</Link>}
          </nav>
          <Link className={styles.signInButton} href={signedIn ? "/" : "/sign-in"}>{signedIn ? "Logout" : "Sign In"}</Link>
        </div>
      </header>
      {children}
      <footer className={styles.footer}>
        <div>
          <strong>StonksInHand</strong>
          <p>&copy; 2024 StonksInHand. Powered by AI, verified by sources.</p>
        </div>
        <nav aria-label="Footer">
          <a href="#">About</a>
          <a href="#">Terms</a>
          <a href="#">Data Sources</a>
        </nav>
      </footer>
    </main>
  )
}

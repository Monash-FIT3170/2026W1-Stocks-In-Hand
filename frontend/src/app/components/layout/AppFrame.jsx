"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { apiFetch } from "../../lib/api"
import { isCognitoAuthEnabled } from "../../../auth/cognito"
import styles from "./AppFrame.module.css"

// Shared app chrome for every prototype page.
// Use this component when a page should have the standard StonksInHand nav and footer.
// The active prop controls which nav item is underlined, and signedIn toggles the
// watchlist/logout variant shown in the Figma prototype. Avoid placing page-specific
// layout here, because changing this file affects every frontend route.
export function AppFrame({
  active,
  signedIn = false,
  children,
}) {
  const [hasSession, setHasSession] = useState(signedIn)

  useEffect(() => {
    let cancelled = false
    setHasSession(signedIn)

    async function loadSession() {
      try {
        const response = await apiFetch("/auth/me", {
          credentials: "include",
        })

        if (cancelled) {
          return
        }

        if (response.ok) {
          setHasSession(true)
          return
        }

        if (!response.ok) {
          setHasSession(false)
        }
      } catch {
        setHasSession(false)
      }
    }

    loadSession()

    return () => {
      cancelled = true
    }
  }, [signedIn])

  return (
    <main className={styles.appShell}>
      <header className={styles.topNav}>
        <div className={styles.navInner}>
          <Link className={styles.brandButton} href="/">StonksInHand</Link>
          <nav className={styles.navLinks} aria-label="Primary">
            <Link className={active === "home" ? styles.activeNavLink : styles.navLink} href="/">Home</Link>
            <Link className={active === "announcements" ? styles.activeNavLink : styles.navLink} href="/announcements">Announcements</Link>
            {hasSession && <Link className={active === "watchlist" ? styles.activeNavLink : styles.navLink} href="/watchlist">My Watchlist</Link>}
            {hasSession && isCognitoAuthEnabled() ? <Link className={styles.navLink} href="/mfa-setup">Security</Link> : null}
          </nav>
          <Link className={styles.signInButton} href={hasSession ? "/sign-out" : "/sign-in"}>{hasSession ? "Logout" : "Sign In"}</Link>
        </div>
      </header>
      {children}
      <footer className={styles.footer}>
        <div>
          <strong>StonksInHand</strong>
          <p>2026 StonksInHand. Powered by AI, verified by sources.</p>
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

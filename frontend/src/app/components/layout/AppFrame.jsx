"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import styles from "./AppFrame.module.css"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
const AUTH_STORAGE_KEY = "stonks_signed_in"

function hasStoredSession() {
  if (typeof window === "undefined") {
    return false
  }

  return window.localStorage.getItem(AUTH_STORAGE_KEY) === "true"
}

function storeSessionHint(isSignedIn) {
  if (typeof window === "undefined") {
    return
  }

  if (isSignedIn) {
    window.localStorage.setItem(AUTH_STORAGE_KEY, "true")
  } else {
    window.localStorage.removeItem(AUTH_STORAGE_KEY)
  }
}

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
  const [hasSession, setHasSession] = useState(() => signedIn || hasStoredSession())

  useEffect(() => {
    let cancelled = false

    async function loadSession() {
      try {
        const response = await fetch(`${API_URL}/auth/me`, {
          credentials: "include",
        })

        if (cancelled) {
          return
        }

        if (response.ok) {
          storeSessionHint(true)
          setHasSession(true)
          return
        }

        if (response.status === 401) {
          storeSessionHint(false)
          setHasSession(false)
          return
        }

        if (!response.ok) {
          storeSessionHint(false)
          setHasSession(false)
        }
      } catch {
        storeSessionHint(false)
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
          </nav>
          <Link className={styles.signInButton} href={hasSession ? "/sign-out" : "/sign-in"}>{hasSession ? "Logout" : "Sign In"}</Link>
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

"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"
import { apiFetch } from "../../lib/api"
import styles from "./AppFrame.module.css"

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

function titleForPath(pathname) {
  if (pathname === "/") return "Home"
  if (pathname.startsWith("/ticker/")) {
    const [, , rawSymbol, section] = pathname.split("/")
    const symbol = (rawSymbol || "Ticker").toUpperCase()
    const suffix = section === "news" ? "News" : section === "deep-dive" ? "Deep dive" : "Brief"
    return `${symbol} ${suffix}`
  }
  if (pathname.startsWith("/announcements")) return "Announcements"
  if (pathname.startsWith("/watchlist")) return "My watchlist"
  if (pathname.startsWith("/search")) return "Company search"
  if (pathname.startsWith("/sign-in")) return "Sign in"
  if (pathname.startsWith("/sign-up")) return "Create account"
  if (pathname.startsWith("/about")) return "About"
  if (pathname.startsWith("/terms")) return "Terms"
  if (pathname.startsWith("/data-sources")) return "Data sources"
  return "Page not found"
}

export function AppFrame({ children }) {
  const pathname = usePathname() || "/"
  const [hasSession, setHasSession] = useState(hasStoredSession)
  const routeTitle = titleForPath(pathname)
  const active = pathname.startsWith("/announcements")
    ? "announcements"
    : pathname.startsWith("/watchlist")
      ? "watchlist"
      : pathname === "/"
        ? "home"
        : null

  useEffect(() => {
    let cancelled = false
    setHasSession(hasStoredSession())
    const updateSessionHint = () => setHasSession(hasStoredSession())
    window.addEventListener("stonks-auth-changed", updateSessionHint)

    async function loadSession() {
      try {
        const response = await apiFetch("/auth/me", {
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
      window.removeEventListener("stonks-auth-changed", updateSessionHint)
    }
  }, [])

  useEffect(() => {
    document.title = `${routeTitle} | StonksInHand`
  }, [routeTitle])

  return (
    <div className={styles.appShell}>
      <a className={styles.skipLink} href="#main-content">Skip to main content</a>
      <header className={styles.topNav}>
        <div className={styles.navInner}>
          <Link className={styles.brandButton} href="/">StonksInHand</Link>
          <nav className={styles.navLinks} aria-label="Primary">
            <Link aria-current={active === "home" ? "page" : undefined} className={active === "home" ? styles.activeNavLink : styles.navLink} href="/">Home</Link>
            <Link aria-current={active === "announcements" ? "page" : undefined} className={active === "announcements" ? styles.activeNavLink : styles.navLink} href="/announcements">Announcements</Link>
            {hasSession && <Link aria-current={active === "watchlist" ? "page" : undefined} className={active === "watchlist" ? styles.activeNavLink : styles.navLink} href="/watchlist">My Watchlist</Link>}
          </nav>
          <Link className={styles.signInButton} href={hasSession ? "/sign-out" : "/sign-in"}>{hasSession ? "Logout" : "Sign In"}</Link>
        </div>
      </header>
      <p className={styles.routeAnnouncer} aria-live="polite" aria-atomic="true">{routeTitle}</p>
      <main className={styles.mainContent} id="main-content" tabIndex="-1">
        {children}
      </main>
      <footer className={styles.footer}>
        <div>
          <strong>StonksInHand</strong>
          <p>2026 StonksInHand. AI-assisted briefs with linked source material.</p>
        </div>
        <nav aria-label="Footer">
          <Link href="/about">About</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/data-sources">Data Sources</Link>
        </nav>
      </footer>
    </div>
  )
}

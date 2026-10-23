"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import { apiFetch } from "../../lib/api"
import { isCognitoAuthEnabled } from "../../../auth/cognito"
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
  if (pathname.startsWith("/settings/profile")) return "Profile settings"
  if (pathname.startsWith("/settings/notifications")) return "Alert settings"
  if (pathname.startsWith("/unsubscribe")) return "Unsubscribe"
  if (pathname.startsWith("/search")) return "Company search"
  if (pathname.startsWith("/sign-in")) return "Sign in"
  if (pathname.startsWith("/sign-up")) return "Create account"
  if (pathname.startsWith("/confirm-sign-up")) return "Confirm account"
  if (pathname.startsWith("/forgot-password")) return "Reset password"
  if (pathname.startsWith("/reset-password")) return "Choose a new password"
  if (pathname.startsWith("/mfa-setup")) return "Authenticator setup"
  if (pathname.startsWith("/about")) return "About"
  if (pathname.startsWith("/terms")) return "Terms"
  if (pathname.startsWith("/data-sources")) return "Data sources"
  return "Page not found"
}

export function AppFrame({ children }) {
  const pathname = usePathname() || "/"
  const [hasSession, setHasSession] = useState(false)
  const [openMenu, setOpenMenu] = useState(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [isCompact, setIsCompact] = useState(false)
  const menuButtonRefs = useRef({})
  const headerRef = useRef(null)
  const mobileButtonRef = useRef(null)
  const routeTitle = titleForPath(pathname)
  const normalizedPath = pathname.replace(/\/$/, "") || "/"
  const publicPage = ["/", "/about", "/data-sources", "/terms"].includes(normalizedPath)
  const active = pathname.startsWith("/announcements")
    ? "announcements"
    : pathname.startsWith("/search")
      ? "search"
    : pathname.startsWith("/watchlist")
      ? "watchlist"
      : pathname.startsWith("/settings/profile")
        ? "profile-settings"
      : pathname.startsWith("/settings/notifications")
        ? "alert-settings"
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

  useEffect(() => {
    setOpenMenu(null)
    setMobileOpen(false)
  }, [pathname])

  useEffect(() => {
    function handlePointerDown(event) {
      if (openMenu && !headerRef.current?.contains(event.target)) setOpenMenu(null)
    }

    function handleKeyDown(event) {
      if (event.key !== "Escape") return
      if (openMenu) {
        setOpenMenu(null)
        menuButtonRefs.current[openMenu]?.focus()
      }
      setMobileOpen(false)
      if (mobileOpen) mobileButtonRef.current?.focus()
    }

    document.addEventListener("pointerdown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [openMenu, mobileOpen])

  useEffect(() => {
    let frame = 0

    function updateCompactState() {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => {
        setIsCompact(window.scrollY > 56)
      })
    }

    updateCompactState()
    window.addEventListener("scroll", updateCompactState, { passive: true })
    return () => {
      window.cancelAnimationFrame(frame)
      window.removeEventListener("scroll", updateCompactState)
    }
  }, [])

  useEffect(() => {
    if (!mobileOpen) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    const desktop = window.matchMedia("(min-width: 768px)")
    function closeOnDesktop() {
      if (!desktop.matches) return
      if (document.activeElement?.closest("#mobile-navigation") || document.activeElement === mobileButtonRef.current) {
        headerRef.current?.querySelector("a")?.focus()
      }
      setMobileOpen(false)
    }
    desktop.addEventListener("change", closeOnDesktop)
    closeOnDesktop()
    return () => {
      document.body.style.overflow = previousOverflow
      desktop.removeEventListener("change", closeOnDesktop)
    }
  }, [mobileOpen])

  const researchLinks = [
    { href: "/search", title: "Search" },
    { href: "/announcements", title: "Market feed" },
    ...(hasSession ? [{ href: "/watchlist", title: "My watchlist" }] : []),
  ]
  const aboutLinks = [
    { href: "/about", title: "About StonksInHand", description: "How source-aware research is prepared" },
    { href: "/terms", title: "Terms of use", description: "Important limits and usage information" },
    { href: "/data-sources", title: "Data sources", description: "Understand the records behind each brief" },
  ]
  const aboutMenu = {
    heading: "Trust and transparency",
    description: "See how the platform works, what it uses, and where its limits sit.",
    links: aboutLinks,
  }
  const currentMenu = openMenu === "about" ? aboutMenu : null

  return (
    <div className={styles.appShell}>
      <a className={styles.skipLink} href="#main-content" inert={mobileOpen || undefined}>Skip to main content</a>
      <header className={`${styles.topNav} ${isCompact && publicPage ? styles.topNavCompact : ""}`} ref={headerRef}>
        <div className={styles.navInner}>
          <Link aria-label="StonksInHand home" className={styles.brandButton} href="/">
            <span className={styles.brandMark} aria-hidden="true"><i /><i /><i /></span>
            <span>StonksInHand</span>
          </Link>
          <nav className={styles.navLinks} aria-label="Primary">
            <Link aria-current={active === "search" ? "page" : undefined} className={active === "search" ? styles.activeNavLink : styles.navLink} href="/search">Search</Link>
            <Link aria-current={active === "announcements" ? "page" : undefined} className={active === "announcements" ? styles.activeNavLink : styles.navLink} href="/announcements">Market feed</Link>
            {hasSession && <Link aria-current={active === "watchlist" ? "page" : undefined} className={active === "watchlist" ? styles.activeNavLink : styles.navLink} href="/watchlist">My watchlist</Link>}
            <button aria-controls="desktop-mega-menu" aria-expanded={openMenu === "about"} className={`${styles.navLink} ${openMenu === "about" ? styles.openNavLink : ""}`} onClick={() => setOpenMenu((value) => value === "about" ? null : "about")} ref={(node) => { menuButtonRefs.current.about = node }} type="button">
              About <span aria-hidden="true" className={styles.navToggle}>+</span>
            </button>
          </nav>
          <div className={styles.navActions}>
            {hasSession && <Link aria-current={active === "profile-settings" ? "page" : undefined} className={styles.settingsLink} href="/settings/profile">Profile</Link>}
            {hasSession && <Link aria-current={active === "alert-settings" ? "page" : undefined} className={styles.settingsLink} href="/settings/notifications">Alerts</Link>}
            {hasSession && isCognitoAuthEnabled() ? <Link className={styles.settingsLink} href="/mfa-setup">Security</Link> : null}
            <Link className={styles.signInButton} href={hasSession ? "/sign-out" : "/sign-in"}>{hasSession ? "Sign out" : "Sign in"}</Link>
          </div>
          <button ref={mobileButtonRef} aria-controls="mobile-navigation" aria-expanded={mobileOpen} aria-label={mobileOpen ? "Close navigation" : "Open navigation"} className={styles.mobileMenuButton} onClick={() => setMobileOpen((value) => !value)} type="button"><span /><span /></button>
        </div>
        <div className={`${styles.megaMenuWrap} ${currentMenu ? styles.megaMenuWrapOpen : ""}`} id="desktop-mega-menu">
          <div className={`${styles.megaMenu}`}>
            <div className={styles.megaMenuIntro}><span>{currentMenu?.heading}</span><p>{currentMenu?.description}</p></div>
            <div className={`${styles.megaMenuGrid}`}>
              {currentMenu?.links.map((item) => <Link href={item.href} key={item.href}><strong>{item.title}</strong><span>{item.description}</span></Link>)}
            </div>
          </div>
        </div>
        <div className={`${styles.mobilePanel} ${mobileOpen ? styles.mobilePanelOpen : ""}`} id="mobile-navigation">
          <nav aria-label="Mobile">
            <span className={styles.mobileSectionLabel}>Explore</span>
            {researchLinks.map((item) => <Link href={item.href} key={item.href}>{item.title}</Link>)}
            <span className={styles.mobileSectionLabel}>About</span>
            {aboutLinks.map((item) => <Link href={item.href} key={item.href}>{item.title}</Link>)}
          </nav>
          <div className={styles.mobilePanelFooter}>
            {hasSession && <Link href="/settings/profile">Profile</Link>}
            {hasSession && <Link href="/settings/notifications">Alert settings</Link>}
            {hasSession && isCognitoAuthEnabled() ? <Link href="/mfa-setup">Security</Link> : null}
            <Link className={styles.mobileAccountAction} href={hasSession ? "/sign-out" : "/sign-in"}>{hasSession ? "Sign out" : "Sign in"}</Link>
          </div>
        </div>
      </header>
      <p className={styles.routeAnnouncer} aria-live="polite" aria-atomic="true">{routeTitle}</p>
      <main className={styles.mainContent} id="main-content" tabIndex="-1" inert={mobileOpen || undefined}>
        {children}
      </main>
      <footer className={`${styles.footer} ${publicPage ? "" : styles.footerCompact}`} inert={mobileOpen || undefined}>
        <div className={styles.footerBrand}>
          <strong>StonksInHand</strong>
          <p>ASX company research with the source material kept close.</p>
        </div>
        <div className={styles.footerDirectory}>
          <nav aria-label="Research"><span>Research</span><Link href="/search">Company search</Link><Link href="/announcements">Announcements</Link><Link href="/watchlist">Watchlist</Link></nav>
          <nav aria-label="Company"><span>Company</span><Link href="/about">About</Link><Link href="/terms">Terms</Link><Link href="/data-sources">Data sources</Link></nav>
        </div>
        <p className={styles.footerLegal}>© 2026 StonksInHand. AI-assisted briefs are informational and should be checked against original sources.</p>
      </footer>
    </div>
  )
}

"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useCompanyData } from "./CompanyData"
import { ArrowIcon, ResourceState } from "./CompanyPrimitives"
import styles from "./CompanyWorkspace.module.css"

const views = [{ path: "", label: "Research summary", description: "Understand the company" }, { path: "/news", label: "Source records", description: "Inspect the evidence" }, { path: "/deep-dive", label: "Deep dive", description: "Read the research history" }]

export function CompanyWorkspace({ children }) {
  const company = useCompanyData()
  const pathname = (usePathname() || "").replace(/\/$/, "")
  const base = `/ticker/${encodeURIComponent(company.symbol)}`
  const overview = company.overview
  return <div className={styles.workspace}>
    <header className={styles.companyHeader}>
      <div className={styles.identity}><Link className={styles.backLink} href="/search">Company search</Link><div className={styles.companyName}><span className={styles.symbol}>{company.symbol}</span><p>{overview?.company_name || `ASX:${company.symbol}`}</p></div><p>{overview?.sector || "ASX company research"}<span className={styles.identityDate}>Latest source {overview?.last_updated && overview.last_updated !== "N/A" ? overview.last_updated : "date unavailable"}</span></p></div>
      <div className={styles.quote} aria-label="Latest available quote"><span>Latest available quote</span><strong>{overview?.current_price || "N/A"}</strong><span>{overview?.day_change && overview.day_change !== "N/A" ? `${overview.day_change} daily change` : "Daily change unavailable"}</span></div>
      <Link className={styles.watchlistLink} href="/watchlist">Open watchlist<ArrowIcon /></Link>
    </header>
    <div className={styles.workspaceGrid}>
      <aside className={styles.navigationRail}>
        <nav aria-label={`${company.symbol} research views`}>{views.map((view) => {
          const href = base + view.path
          const active = pathname === href
          return <Link className={active ? styles.activeView : styles.viewLink} aria-current={active ? "page" : undefined} href={href} key={view.path}><span>{view.label}</span></Link>
        })}</nav>
        <Link className={styles.sourcePolicy} href="/data-sources">About the data<ArrowIcon /></Link>
      </aside>
      <div className={styles.workArea}>{company.isLoading ? <ResourceState resource={company} name="Company research" /> : <>{overview?.is_preview || company.is_preview ? <p className={styles.previewNotice}>Local preview · Illustrative company research</p> : null}{company.error ? <div className={styles.briefError}><ResourceState resource={company} name="Company brief" /></div> : null}{children}</>}</div>
    </div>
  </div>
}

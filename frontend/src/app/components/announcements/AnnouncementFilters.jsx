"use client"

import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import styles from "../../page.module.css"

const SECTORS = [
  "Materials",
  "Financials",
  "Health Care",
  "Consumer Staples",
  "Industrials",
  "Technology",
  "Energy",
]

function buildFilterHref({ today, sector }) {
  const params = new URLSearchParams()
  if (today) {
    params.set("today", "true")
  }
  if (sector) {
    params.set("sector", sector)
  }
  const query = params.toString()
  return query ? `/announcements?${query}` : "/announcements"
}

export function AnnouncementFilters({ today = false, sector = "" }) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const todayHref = buildFilterHref({ today: !today, sector })

  function handleSectorChange(event) {
    const params = new URLSearchParams(searchParams.toString())
    const nextSector = event.target.value
    if (nextSector) {
      params.set("sector", nextSector)
    } else {
      params.delete("sector")
    }
    const query = params.toString()
    router.push(query ? `/announcements?${query}` : "/announcements")
  }

  return (
    <div className={styles.filterPills}>
      <select aria-label="Filter by sector" onChange={handleSectorChange} value={sector}>
        <option value="">All sectors</option>
        {SECTORS.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <Link className={today ? styles.activeFilter : ""} href={todayHref}>
        Today
      </Link>
    </div>
  )
}

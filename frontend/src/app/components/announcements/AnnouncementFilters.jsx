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

function buildFilterHref({ today, sector, startDate = "", endDate = "" }) {
  const params = new URLSearchParams()
  if (today) {
    params.set("today", "true")
  }
  if (sector) {
    params.set("sector", sector)
  }
  if (startDate) {
    params.set("start_date", startDate)
  }
  if (endDate) {
    params.set("end_date", endDate)
  }
  const query = params.toString()
  return query ? `/announcements?${query}` : "/announcements"
}

function formatDisplayDate(value) {
  if (!value) {
    return ""
  }
  const [year, month, day] = value.split("-")
  return `${day}/${month}/${year}`
}

export function AnnouncementFilters({ today = false, sector = "", startDate = "", endDate = "" }) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const hasFilters = today || sector || startDate || endDate
  const todayHref = buildFilterHref({ today: !today, sector })
  const dateSummary = startDate || endDate
    ? `${startDate ? formatDisplayDate(startDate) : "Any date"} - ${endDate ? formatDisplayDate(endDate) : "Now"}`
    : ""

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

  function handleDateChange(key, value) {
    const params = new URLSearchParams(searchParams.toString())
    params.delete("today")
    if (value) {
      params.set(key, value)
    } else {
      params.delete(key)
    }
    const query = params.toString()
    router.push(query ? `/announcements?${query}` : "/announcements")
  }

  return (
    <div className={styles.filterPanel}>
      <div className={styles.filterPills}>
        <select aria-label="Filter by sector" onChange={handleSectorChange} value={sector}>
          <option value="">All sectors</option>
          {SECTORS.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <Link className={today ? styles.activeFilter : ""} href={todayHref}>
          Today
        </Link>
        {hasFilters ? <Link href="/announcements">Clear</Link> : null}
      </div>
      <div className={styles.dateRangeFilters}>
        <label>
          <span>From</span>
          <input
            aria-label="Start date"
            onChange={(event) => handleDateChange("start_date", event.target.value)}
            type="date"
            value={startDate}
          />
        </label>
        <label>
          <span>To</span>
          <input
            aria-label="End date"
            onChange={(event) => handleDateChange("end_date", event.target.value)}
            type="date"
            value={endDate}
          />
        </label>
      </div>
      {dateSummary ? <p className={styles.dateRangeSummary}>{dateSummary}</p> : null}
    </div>
  )
}

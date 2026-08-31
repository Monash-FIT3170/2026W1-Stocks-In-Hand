"use client"

import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import styles from "../research/ResearchSurface.module.css"

const SECTORS = [
  "Materials",
  "Financials",
  "Health Care",
  "Consumer Staples",
  "Consumer Discretionary",
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
  const allHref = buildFilterHref({ today: false, sector })
  const dateSummary = startDate || endDate
    ? `${startDate ? formatDisplayDate(startDate) : "Any date"} – ${endDate ? formatDisplayDate(endDate) : "Now"}`
    : ""
  const dateLabel = today ? "Today" : dateSummary || "All dates"

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
    <section aria-label="Announcement filters" className={styles.filterPanel}>
      <div className={styles.panelHeading}>
        <div>
          <span className={styles.panelKicker}>Market filters</span>
          <h2>Refine the feed</h2>
        </div>
        {hasFilters ? <Link className={styles.resetLink} href="/announcements">Reset all</Link> : null}
      </div>
      <div className={styles.filterFields}>
        <label className={styles.field}>
          <span>Sector</span>
          <select aria-label="Filter by sector" onChange={handleSectorChange} value={sector}>
            <option value="">All market sectors</option>
            {SECTORS.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <details className={styles.dateRangePicker}>
          <summary aria-label={`Date range: ${dateLabel}`}>
            <span><small>Date range</small><strong>{dateLabel}</strong></span>
            <i aria-hidden="true" />
          </summary>
          <div className={styles.dateRangePopover}>
            <div className={styles.rangePresets} aria-label="Quick date filters">
              <Link className={`${styles.rangePreset} ${!today && !startDate && !endDate ? styles.rangePresetActive : ""}`} href={allHref}>All dates</Link>
              <Link aria-current={today ? "true" : undefined} className={`${styles.rangePreset} ${today ? styles.rangePresetActive : ""}`} href={todayHref}>Today</Link>
            </div>
            <div className={styles.dateRangeInputs}>
              <label className={styles.dateField}>
                <span>From</span>
                <input aria-label="Start date" onChange={(event) => handleDateChange("start_date", event.target.value)} type="date" value={startDate} />
              </label>
              <label className={styles.dateField}>
                <span>To</span>
                <input aria-label="End date" onChange={(event) => handleDateChange("end_date", event.target.value)} type="date" value={endDate} />
              </label>
            </div>
            <p>Dates use Sydney market time.</p>
          </div>
        </details>
      </div>
    </section>
  )
}

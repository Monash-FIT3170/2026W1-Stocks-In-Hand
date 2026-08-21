"use client"

import { Suspense, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { AnnouncementCard } from "../components/announcements/AnnouncementCard"
import { AnnouncementFilters } from "../components/announcements/AnnouncementFilters"
import { TrendingStocks } from "../components/announcements/TrendingStocks"
import { AppFrame } from "../components/layout/AppFrame"
import { fetchAnnouncements, fetchTrendingAnnouncements } from "../lib/api"
import styles from "../page.module.css"

function formatAnnouncementTimestamp(value) {
  if (!value) {
    return "Date unavailable"
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return "Date unavailable"
  }

  const datePart = new Intl.DateTimeFormat("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Australia/Sydney",
  }).format(date)

  const hasSpecificTime = /T/.test(value)
    && !/T00:00:00(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/.test(value)
  if (!hasSpecificTime) {
    return datePart
  }

  const timePart = new Intl.DateTimeFormat("en-AU", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Australia/Sydney",
  }).format(date)

  return `${datePart}, ${timePart}`
}

// Announcements route for "/announcements".
// This page renders only DB-backed announcement data so empty/error states expose
// integration problems immediately.
function AnnouncementsContent() {
  const searchParams = useSearchParams()
  const query = searchParams.toString()
  const filters = useMemo(() => {
    const params = new URLSearchParams(query)
    return {
      today: params.get("today") === "true",
      sector: params.get("sector") || "",
      startDate: params.get("start_date") || "",
      endDate: params.get("end_date") || "",
    }
  }, [query])
  const [state, setState] = useState({
    announcementCards: [],
    errorMessage: "",
    isLoading: true,
    trendingStocks: [],
  })

  useEffect(() => {
    let cancelled = false

    async function loadAnnouncements() {
      setState((current) => ({ ...current, errorMessage: "", isLoading: true }))

      try {
        const [announcements, trendingStocks] = await Promise.all([
          fetchAnnouncements(filters),
          fetchTrendingAnnouncements({ days: 7, limit: 4 }),
        ])
        if (!cancelled) {
          setState({
            announcementCards: announcements.map((item) => ({
              ...item,
              time: formatAnnouncementTimestamp(item.published_at),
            })),
            errorMessage: "",
            isLoading: false,
            trendingStocks,
          })
        }
      } catch {
        if (!cancelled) {
          setState({
            announcementCards: [],
            errorMessage: "Announcements are unavailable right now. Please try again once the backend is running.",
            isLoading: false,
            trendingStocks: [],
          })
        }
      }
    }

    loadAnnouncements()
    return () => {
      cancelled = true
    }
  }, [filters])

  const {
    announcementCards,
    errorMessage,
    isLoading,
    trendingStocks,
  } = state
  const { today, sector, startDate, endDate } = filters

  return (
    <AppFrame active="announcements">
      <section className={styles.contentPage}>
        <div className={styles.announcementsHero}>
          <div>
            <h1>ASX Announcements</h1>
            <p>Real-time intelligence from the Australian Securities Exchange. Decoded by AI to give you the signal within the noise.</p>
          </div>
          <div className={styles.announcementControls}>
            <AnnouncementFilters endDate={endDate} sector={sector} startDate={startDate} today={today} />
            <TrendingStocks stocks={trendingStocks} />
          </div>
        </div>
        <div className={styles.announcementList}>
          {isLoading ? <div className={styles.emptyCard}><h3>Loading announcements...</h3></div> : null}
          {errorMessage ? <div className={styles.emptyCard}><h3>{errorMessage}</h3></div> : null}
          {!isLoading && !errorMessage && announcementCards.length === 0 ? <div className={styles.emptyCard}><h3>No ASX announcements found.</h3><p>New announcements will appear here after they are stored in the database.</p></div> : null}
          {announcementCards.map((item) => <AnnouncementCard item={item} key={item.id} />)}
        </div>
      </section>
    </AppFrame>
  )
}

export default function AnnouncementsRoute() {
  return (
    <Suspense fallback={<AppFrame active="announcements"><section className={styles.contentPage}>Loading announcements...</section></AppFrame>}>
      <AnnouncementsContent />
    </Suspense>
  )
}

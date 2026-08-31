"use client"

import { Suspense, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { AnnouncementCard } from "../components/announcements/AnnouncementCard"
import { AnnouncementFilters } from "../components/announcements/AnnouncementFilters"
import { TrendingStocks } from "../components/announcements/TrendingStocks"
import { fetchAnnouncements, fetchTrendingAnnouncements } from "../lib/api"
import styles from "../page.module.css"

const ANNOUNCEMENT_PAGE_SIZE = 6

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
  const [attempt, setAttempt] = useState(0)
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
    hasMore: false,
    isLoading: true,
    isLoadingMore: false,
    loadMoreError: "",
    trendingStocks: [],
  })

  useEffect(() => {
    let cancelled = false

    async function loadAnnouncements() {
      setState((current) => ({ ...current, errorMessage: "", isLoading: true }))

      try {
        const [announcements, trendingStocks] = await Promise.all([
          fetchAnnouncements({ ...filters, limit: ANNOUNCEMENT_PAGE_SIZE }),
          fetchTrendingAnnouncements({ days: 7, limit: 4 }),
        ])
        if (!cancelled) {
          setState({
            announcementCards: announcements.map((item) => ({
              ...item,
              time: formatAnnouncementTimestamp(item.published_at),
            })),
            errorMessage: "",
            hasMore: announcements.length === ANNOUNCEMENT_PAGE_SIZE,
            isLoading: false,
            isLoadingMore: false,
            loadMoreError: "",
            trendingStocks,
          })
        }
      } catch {
        if (!cancelled) {
          setState({
            announcementCards: [],
            errorMessage: "Announcements are unavailable right now. Check your connection and try again.",
            hasMore: false,
            isLoading: false,
            isLoadingMore: false,
            loadMoreError: "",
            trendingStocks: [],
          })
        }
      }
    }

    loadAnnouncements()
    return () => {
      cancelled = true
    }
  }, [attempt, filters])

  async function loadMoreAnnouncements() {
    setState((current) => ({ ...current, isLoadingMore: true, loadMoreError: "" }))
    try {
      const announcements = await fetchAnnouncements({
        ...filters,
        limit: ANNOUNCEMENT_PAGE_SIZE,
        offset: state.announcementCards.length,
      })
      const nextCards = announcements.map((item) => ({
        ...item,
        time: formatAnnouncementTimestamp(item.published_at),
      }))
      setState((current) => ({
        ...current,
        announcementCards: [...current.announcementCards, ...nextCards],
        hasMore: announcements.length === ANNOUNCEMENT_PAGE_SIZE,
        isLoadingMore: false,
      }))
    } catch {
      setState((current) => ({
        ...current,
        isLoadingMore: false,
        loadMoreError: "More announcements could not be loaded. Try again.",
      }))
    }
  }

  const {
    announcementCards,
    errorMessage,
    hasMore,
    isLoading,
    isLoadingMore,
    loadMoreError,
    trendingStocks,
  } = state
  const { today, sector, startDate, endDate } = filters

  return (
    <section className={styles.contentPage}>
        <div className={styles.announcementsHero}>
          <div>
            <h1>ASX Announcements</h1>
            <p>Recent ASX filings and publisher reports, summarised in plain English with links back to available source material.</p>
          </div>
          <div className={styles.announcementControls}>
            <AnnouncementFilters endDate={endDate} sector={sector} startDate={startDate} today={today} />
            <TrendingStocks stocks={trendingStocks} />
          </div>
        </div>
        <div className={styles.announcementList}>
          {isLoading ? <div className={styles.contentSkeleton} aria-live="polite">Loading announcements…</div> : null}
          {errorMessage ? <div className={styles.emptyCard} role="alert"><h2>Could not load announcements</h2><p>{errorMessage}</p><button className={styles.secondaryButton} onClick={() => setAttempt((value) => value + 1)} type="button">Try again</button></div> : null}
          {!isLoading && !errorMessage && announcementCards.length === 0 ? <div className={styles.emptyCard}><h2>No ASX announcements found</h2><p>Adjust the filters or check back after the next pipeline run.</p></div> : null}
          {announcementCards.map((item) => <AnnouncementCard item={item} key={item.id} />)}
          {loadMoreError ? <p className={styles.authError} role="alert">{loadMoreError}</p> : null}
          {hasMore ? (
            <button className={styles.loadMoreButton} disabled={isLoadingMore} onClick={loadMoreAnnouncements} type="button">
              {isLoadingMore ? "Loading more…" : "Show more announcements"}
            </button>
          ) : null}
        </div>
    </section>
  )
}

export default function AnnouncementsRoute() {
  return (
    <Suspense fallback={<section className={styles.contentPage}><div className={styles.contentSkeleton}>Loading announcements…</div></section>}>
      <AnnouncementsContent />
    </Suspense>
  )
}

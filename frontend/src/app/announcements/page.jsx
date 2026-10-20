"use client"

import { Suspense, useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { AnnouncementCard } from "../components/announcements/AnnouncementCard"
import { AnnouncementFilters } from "../components/announcements/AnnouncementFilters"
import { TrendingStocks } from "../components/announcements/TrendingStocks"
import { groupByPublicationDate } from "../components/announcements/recordPresentation"
import { ArrowIcon } from "../components/company/CompanyPrimitives"
import { fetchAnnouncements, fetchTrendingAnnouncements } from "../lib/api"
import { isContentTopic, topicLabel } from "../lib/contentTopics"
import { appendAnnouncementPage } from "./pagination"
import pageStyles from "../page.module.css"
import styles from "../components/research/ResearchSurface.module.css"

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

// Market updates route for "/announcements".
// This page renders only DB-backed source data so empty/error states expose
// integration problems immediately.
function AnnouncementsContent() {
  const searchParams = useSearchParams()
  const [attempt, setAttempt] = useState(0)
  const feedGeneration = useRef(0)
  const query = searchParams.toString()
  const filters = useMemo(() => {
    const params = new URLSearchParams(query)
    return {
      today: params.get("today") === "true",
      sector: params.get("sector") || "",
      // An unknown topic is ignored rather than sent, so a stale link still shows the feed.
      topic: isContentTopic(params.get("topic")) ? params.get("topic") : "",
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
    nextOffset: 0,
    trendingStocks: [],
  })

  useEffect(() => {
    let cancelled = false
    feedGeneration.current += 1

    async function loadAnnouncements() {
      setState((current) => ({ ...current, announcementCards: [], hasMore: false, isLoadingMore: false, loadMoreError: "", errorMessage: "", isLoading: true }))

      try {
        const [announcements, trendingStocks] = await Promise.all([
          fetchAnnouncements({ ...filters, limit: ANNOUNCEMENT_PAGE_SIZE }),
          fetchTrendingAnnouncements({ days: 7, limit: 4 }),
        ])
        if (!cancelled) {
          const firstPage = announcements.map((item) => ({
              ...item,
              time: formatAnnouncementTimestamp(item.published_at),
            }))
          const page = appendAnnouncementPage([], firstPage, 0)
          setState({
            announcementCards: page.announcementCards,
            errorMessage: "",
            hasMore: announcements.length === ANNOUNCEMENT_PAGE_SIZE,
            isLoading: false,
            isLoadingMore: false,
            loadMoreError: "",
            nextOffset: page.nextOffset,
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
            nextOffset: 0,
            trendingStocks: [],
          })
        }
      }
    }

    loadAnnouncements()
    return () => {
      cancelled = true
      feedGeneration.current += 1
    }
  }, [attempt, filters])

  async function loadMoreAnnouncements() {
    const generation = feedGeneration.current
    setState((current) => ({ ...current, isLoadingMore: true, loadMoreError: "" }))
    try {
      const announcements = await fetchAnnouncements({
        ...filters,
        limit: ANNOUNCEMENT_PAGE_SIZE,
        offset: state.nextOffset,
      })
      if (generation !== feedGeneration.current) return
      const nextCards = announcements.map((item) => ({
        ...item,
        time: formatAnnouncementTimestamp(item.published_at),
      }))
      setState((current) => {
        const page = appendAnnouncementPage(
          current.announcementCards,
          nextCards,
          current.nextOffset,
        )
        return {
          ...current,
          announcementCards: page.announcementCards,
          hasMore: announcements.length === ANNOUNCEMENT_PAGE_SIZE,
          isLoadingMore: false,
          nextOffset: page.nextOffset,
        }
      })
    } catch {
      if (generation !== feedGeneration.current) return
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
  const { today, sector, topic, startDate, endDate } = filters
  const isPreview = announcementCards.some((item) => item.is_preview)
    || trendingStocks.some((item) => typeof item === "object" && item?.is_preview)

  return (
    <section className={`${pageStyles.contentPage} ${styles.surface}`}>
        <header className={styles.feedHero}>
          <div className={styles.feedIntro}>
            <h1>Market intelligence, organised by source.</h1>
            <p>Scan the latest ASX filings, publisher coverage, and public discussion—then move directly to the evidence behind each update.</p>
          </div>
          <div className={styles.feedScope}><strong>The material behind the market.</strong><p>Official filings, publisher coverage and public discussion, with their original sources kept in view.</p><Link href="/data-sources">About our sources<ArrowIcon /></Link></div>
        </header>
        {isPreview ? <div className={styles.previewNotice}><strong>Local preview data</strong><span>Illustrative records are shown because the local API is not connected.</span></div> : null}
        <div className={styles.feedWorkbench}>
          <AnnouncementFilters endDate={endDate} sector={sector} startDate={startDate} today={today} topic={topic} />
        </div>
        <div className={styles.feedLayout}><section className={styles.feedReading} aria-labelledby="latest-records-heading">
        <div className={styles.feedHeading}>
          <h2 id="latest-records-heading">{topic ? `Latest records about ${topicLabel(topic).toLowerCase()}` : "Latest source records"}</h2>
          {!isLoading && !errorMessage ? <span>{announcementCards.length} shown</span> : null}
        </div>
        <div className={styles.feedList}>
          {isLoading ? <div className={styles.statePanel} aria-live="polite">Loading source records…</div> : null}
          {errorMessage ? <div className={styles.statePanel} role="alert"><h2>Could not load announcements</h2><p>{errorMessage}</p><button className={styles.secondaryButton} onClick={() => setAttempt((value) => value + 1)} type="button">Try again</button></div> : null}
          {!isLoading && !errorMessage && announcementCards.length === 0 ? <div className={styles.statePanel}><h2>No market updates found</h2><p>{topic ? "No collected records have been tagged with this topic for these filters. Try another topic or clear the topic filter." : "Adjust the filters or collect new ASX, news, and Reddit content."}</p></div> : null}
          {groupByPublicationDate(announcementCards).map((group) => <section className={styles.dateGroup} key={group.label}><h3>{group.label}</h3>{group.items.map((item) => <AnnouncementCard item={item} headingLevel="h4" grouped key={item.id} />)}</section>)}
          {loadMoreError ? <p role="alert">{loadMoreError}</p> : null}
          {hasMore ? (
            <button className={styles.loadMore} disabled={isLoadingMore} onClick={loadMoreAnnouncements} type="button">
              {isLoadingMore ? "Loading more…" : "Show more announcements"}
            </button>
          ) : null}
        </div>
        </section><aside className={styles.feedContext}><TrendingStocks stocks={trendingStocks} /><div className={styles.contextGuide}><h2>Read it at the source.</h2><p>AI-assisted context is a starting point. Open the original material to verify a claim and understand its full context.</p><Link href="/data-sources">How sources are used</Link></div></aside></div>
    </section>
  )
}

export default function AnnouncementsRoute() {
  return (
    <Suspense fallback={<section className={pageStyles.contentPage}><div className={styles.statePanel}>Loading announcements…</div></section>}>
      <AnnouncementsContent />
    </Suspense>
  )
}

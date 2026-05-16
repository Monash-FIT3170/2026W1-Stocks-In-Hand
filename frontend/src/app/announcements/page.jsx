import { AnnouncementCard } from "../components/announcements/AnnouncementCard"
import { TrendingStocks } from "../components/announcements/TrendingStocks"
import { AppFrame } from "../components/layout/AppFrame"
import { EmergingThemes } from "../components/ticker/EmergingThemes"
import { fetchAnnouncements } from "../lib/api"
import styles from "../page.module.css"

function formatAnnouncementTime(value) {
  if (!value) {
    return "Time unavailable"
  }
  return new Intl.DateTimeFormat("en-AU", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}

async function getAnnouncementCards() {
  const announcements = await fetchAnnouncements()
  return announcements.map((item) => ({
    ...item,
    time: formatAnnouncementTime(item.published_at),
  }))
}

// Announcements route for "/announcements".
// This file is intentionally a composition layer: it decides which feed cards and
// sidebar modules appear together, while AnnouncementCard, TrendingStocks, and
// EmergingThemes own the reusable pieces. Filtering buttons are visual only for now;
// future filter state/API calls should be added here or extracted into a small client component.
export default async function AnnouncementsRoute() {
  let announcementCards = []
  let errorMessage = ""

  try {
    announcementCards = await getAnnouncementCards()
  } catch {
    errorMessage = "Announcements are unavailable right now. Please try again once the backend is running."
  }

  return (
    <AppFrame active="announcements">
      <section className={styles.contentPage}>
        <div className={styles.announcementsHero}>
          <div>
            <h1>ASX Announcements</h1>
            <p>Real-time intelligence from the Australian Securities Exchange. Decoded by AI to give you the signal within the noise.</p>
          </div>
          <div className={styles.filterPills}><button type="button">Filter by Sector</button><button type="button">Today</button></div>
        </div>
        <div className={styles.twoColumn}>
          <div className={styles.announcementList}>
            {errorMessage ? <div className={styles.emptyCard}><h3>{errorMessage}</h3></div> : null}
            {!errorMessage && announcementCards.length === 0 ? <div className={styles.emptyCard}><h3>No ASX announcements found.</h3><p>New announcements will appear here after they are stored in the database.</p></div> : null}
            {announcementCards.map((item) => <AnnouncementCard item={item} key={item.id} />)}
          </div>
          <aside className={styles.announcementsAside}>
            <TrendingStocks />
            <EmergingThemes />
          </aside>
        </div>
      </section>
    </AppFrame>
  )
}

import { AnnouncementCard } from "../components/announcements/AnnouncementCard"
import { TrendingStocks } from "../components/announcements/TrendingStocks"
import { AppFrame } from "../components/layout/AppFrame"
import { EmergingThemes } from "../components/ticker/EmergingThemes"
import { announcementCards } from "../mock/announcements"
import styles from "../page.module.css"

// Announcements route for "/announcements".
// This file is intentionally a composition layer: it decides which feed cards and
// sidebar modules appear together, while AnnouncementCard, TrendingStocks, and
// EmergingThemes own the reusable pieces. Filtering buttons are visual only for now;
// future filter state/API calls should be added here or extracted into a small client component.
export default function AnnouncementsRoute() {
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
          <div className={styles.announcementList}>{announcementCards.map((item) => <AnnouncementCard item={item} key={item.title} />)}</div>
          <aside className={styles.announcementsAside}>
            <TrendingStocks />
            <EmergingThemes />
          </aside>
        </div>
      </section>
    </AppFrame>
  )
}

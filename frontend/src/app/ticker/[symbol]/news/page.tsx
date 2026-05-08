import { AnnouncementCard } from "../../../components/announcements/AnnouncementCard"
import { AppFrame } from "../../../components/layout/AppFrame"
import { BriefAside } from "../../../components/ticker/BriefAside"
import { BriefTabs } from "../../../components/ticker/BriefTabs"
import { TickerHeader } from "../../../components/ticker/TickerHeader"
import { announcementCards } from "../../../mock/announcements"
import styles from "../../../page.module.css"

export default function TickerNewsRoute() {
  return (
    <AppFrame active="home">
      <section className={styles.contentPage}>
        <div className={styles.briefShell}>
          <div className={styles.briefMain}>
            <TickerHeader />
            <BriefTabs active="news" />
            <div className={styles.briefContent}><AnnouncementCard item={announcementCards[0]} /></div>
          </div>
          <BriefAside />
        </div>
      </section>
    </AppFrame>
  )
}

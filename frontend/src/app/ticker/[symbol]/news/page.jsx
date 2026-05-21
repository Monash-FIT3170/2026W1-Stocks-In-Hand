import { AnnouncementCard } from "../../../components/announcements/AnnouncementCard"
import { AppFrame } from "../../../components/layout/AppFrame"
import { BriefAside } from "../../../components/ticker/BriefAside"
import { BriefTabs } from "../../../components/ticker/BriefTabs"
import { TickerHeader } from "../../../components/ticker/TickerHeader"
import { fetchTickerBriefAside, fetchTickerNews, fetchTickerOverview } from "../../../lib/api"
import styles from "../../../page.module.css"

// Ticker brief news tab for "/ticker/[symbol]/news".
// This reuses AnnouncementCard and renders only DB-backed ticker announcements.
async function fetchNews(symbol) {
  const [news, overview, aside] = await Promise.all([
    fetchTickerNews(symbol),
    fetchTickerOverview(symbol),
    fetchTickerBriefAside(symbol),
  ])
  return { news, overview, aside }
}

export default async function TickerNewsRoute({ params }) {
  const symbol = params.symbol
  let news, overview, aside
  try {
    ;({ news, overview, aside } = await fetchNews(symbol))
  } catch {
    return (
      <AppFrame active="home">
        <section className={styles.contentPage}>
          <div className={styles.emptyCard}>
            <h3>{symbol} not found</h3>
            <p>This ticker is not in the database yet. It will appear once the data pipeline has run.</p>
          </div>
        </section>
      </AppFrame>
    )
  }

  return (
    <AppFrame active="home">
      <section className={styles.contentPage}>
        <div className={styles.briefShell}>
          <div className={styles.briefMain}>
            <TickerHeader data={overview} />
            <BriefTabs active="news" symbol={symbol} />
            <div className={styles.briefContent}>
              {news.map((item) => (
                <AnnouncementCard item={item} key={item.id} />
              ))}
            </div>
          </div>
          <BriefAside data={aside} />
        </div>
      </section>
    </AppFrame>
  )
}

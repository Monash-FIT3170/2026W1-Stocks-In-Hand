import { AnnouncementCard } from "../../../components/announcements/AnnouncementCard"
import { AppFrame } from "../../../components/layout/AppFrame"
import { BriefAside } from "../../../components/ticker/BriefAside"
import { BriefTabs } from "../../../components/ticker/BriefTabs"
import { TickerHeader } from "../../../components/ticker/TickerHeader"
// import { announcementCards } from "../../../mock/announcements"
import styles from "../../../page.module.css"

// Ticker brief news tab for "/ticker/[symbol]/news".
// This reuses AnnouncementCard from the ASX announcements feed so the team only has
// one announcement-card design to maintain. When the backend is added, filter the
// announcement data by the active ticker symbol and pass those records into the card.
async function fetchNews(symbol) {
  const res = await fetch(`http://backend:8000/tickers/symbol/${symbol}/news-feed`, { cache: 'no-store' })
  const overview = await fetch(`http://backend:8000/tickers/symbol/${symbol}/overview`, { cache: 'no-store' })
  if (!res.ok || !overview.ok) throw new Error("Failed to load data")
  return { news: await res.json(), overview: await overview.json() }
}

export default async function TickerNewsRoute({ params }) {
  const symbol = params.symbol
  const { news, overview } = await fetchNews(symbol)

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
          <BriefAside />
        </div>
      </section>
    </AppFrame>
  )
}

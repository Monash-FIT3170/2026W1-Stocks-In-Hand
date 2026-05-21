import { AppFrame } from "../../../components/layout/AppFrame"
import { BriefAside } from "../../../components/ticker/BriefAside"
import { BriefTabs } from "../../../components/ticker/BriefTabs"
import { DeepDiveTimeline } from "../../../components/ticker/DeepDiveTimeline"
import { TickerHeader } from "../../../components/ticker/TickerHeader"
import { fetchTickerBriefAside, fetchTickerDeepDive, fetchTickerOverview } from "../../../lib/api"
import styles from "../../../page.module.css"

// Ticker brief deep-dive tab for "/ticker/[symbol]/deep-dive".
// Timeline entries come from DB-backed ticker artifacts.
async function fetchDeepDive(symbol) {
  const [timeline, overview, aside] = await Promise.all([
    fetchTickerDeepDive(symbol),
    fetchTickerOverview(symbol),
    fetchTickerBriefAside(symbol),
  ])
  return { timeline, overview, aside }
}

export default async function TickerDeepDiveRoute({ params }) {
  const symbol = params.symbol
  let timeline, overview, aside
  try {
    ;({ timeline, overview, aside } = await fetchDeepDive(symbol))
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
            <BriefTabs active="deep" symbol={symbol} />
            <DeepDiveTimeline timeline={timeline} />
          </div>
          <BriefAside data={aside} />
        </div>
      </section>
    </AppFrame>
  )
}

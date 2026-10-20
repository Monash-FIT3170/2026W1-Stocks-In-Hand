import Link from "next/link"
import styles from "./AnnouncementCard.module.css"
import { TopicChips } from "../topics/TopicChips"
import { companyRoute, meaningfulText, originalUrl, recordSources, sourceKind } from "./recordPresentation"

function Arrow({ external = false }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24">{external ? <path d="M6 18 18 6M6 6h12v12" /> : <path d="M4 12h16m-6-6 6 6-6 6" />}</svg>
}

export function AnnouncementCard({ item, headingLevel = "h3", grouped = false }) {
  const Title = headingLevel
  const company = companyRoute(item.ticker)
  const symbol = item.ticker === "ASX" ? "Market-wide" : item.ticker || "Market-wide"
  const kind = sourceKind(item.source_type || item.tag)
  const about = meaningfulText(item.about, item.title)
  const changed = meaningfulText(item.changed, item.title)
  const matters = meaningfulText(item.matters, item.title)
  const { primary, additional } = recordSources(item)
  const research = [["What changed", changed], ["Research angle", matters]].filter(([, text]) => text && text !== about)
  const hasDetails = research.length > 0 || additional.length > 0

  return <article className={styles.record}>
    <div className={styles.meta}>
      {company ? <Link className={styles.ticker} href={company}>{symbol}</Link> : <span className={styles.ticker}>{symbol}</span>}
      <span className={styles.kind}>{kind}</span>
      {item.source_name && <span className={styles.publisher}>{item.source_name}</span>}
      {(!grouped || /\d{1,2}:\d{2}/.test(item.time || "")) && <time>{item.time || "Date unavailable"}</time>}
    </div>
    <Title className={styles.title}>{item.title || "Untitled source record"}</Title>
    <TopicChips item={item} />
    {about && <p className={styles.excerpt}>{about}</p>}
    {!about && !changed && !matters && <p className={styles.pending}>Analysis pending</p>}
    <div className={styles.actions}>
      {primary ? <a href={primary} target="_blank" rel="noopener noreferrer">{item.source_label || "Open original source"}<Arrow external /></a> : <span className={styles.pending}>Original link unavailable</span>}
      {company && <Link href={`${company}/news`}>Open {symbol} research<Arrow /></Link>}
    </div>
    {hasDetails && <details className={styles.detail}>
      <summary>{research.length ? "Research details" : "Additional sources"}</summary>
      <div className={styles.detailBody}>
        {research.map(([label, text]) => <section key={label}><h4>{label}</h4><p>{text}</p></section>)}
        {additional.length > 0 && <section><h4>Additional evidence</h4>{additional.map((source, index) => <div key={`${source.url}-${index}`}><a href={originalUrl(source.url)} target="_blank" rel="noopener noreferrer">{source.title || source.label || "Original source"}</a>{source.evidence_text && <p>{source.evidence_text}</p>}</div>)}</section>}
      </div>
    </details>}
  </article>
}

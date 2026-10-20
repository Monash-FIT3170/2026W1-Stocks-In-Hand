"use client"

import { useCallback, useEffect, useState } from "react"
import { CONTENT_TOPICS } from "../../lib/contentTopics"
import { fetchTickerDeepDive } from "../../lib/api"
import { useCompanyData } from "./CompanyData"
import { useCompanyResource } from "./useCompanyResource"
import { EmptyState, ResourceState, SourceLinks } from "./CompanyPrimitives"
import { sourceKind } from "../announcements/recordPresentation"
import { hasResearchText } from "./companyFormat"
import { TopicClusters } from "./TopicClusters"
import styles from "./CompanyWorkspace.module.css"
import filterStyles from "./TopicClusters.module.css"

export function DeepDiveNotebook() {
  const [topic, setTopic] = useState("")
  const [indexExpanded, setIndexExpanded] = useState(false)
  useEffect(() => {
    const media = window.matchMedia("(max-width: 650px)")
    const adaptIndex = () => setIndexExpanded(!media.matches)
    adaptIndex()
    media.addEventListener("change", adaptIndex)
    return () => media.removeEventListener("change", adaptIndex)
  }, [])
  const { symbol, isLoading } = useCompanyData()
  const fetchHistory = useCallback((ticker) => fetchTickerDeepDive(ticker, topic), [topic])
  const resource = useCompanyResource(fetchHistory, symbol, !isLoading)
  const events = Array.isArray(resource.data) ? resource.data : []
  return <div className={styles.notebook}>
    <div className={styles.pageHeading} id="history-top"><h1>Deep dive</h1><p>Read the collected research history for {symbol}, one source at a time.</p></div>
    <div className={filterStyles.topicFilter}>
      <label htmlFor="deep-dive-topic">Topic</label>
      <select id="deep-dive-topic" value={topic} onChange={(event) => setTopic(event.target.value)}>
        <option value="">All topics</option>
        {CONTENT_TOPICS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
      {topic && <button type="button" onClick={() => setTopic("")}>Clear topic</button>}
    </div>
    <TopicClusters topic={topic} />
    <ResourceState resource={resource} name="Research history">{events.length ? <>
      <div className={styles.notebookLayout}><nav className={styles.chapterIndex} aria-label="Research history entries"><details className={styles.historyContents} open={indexExpanded} onToggle={(event) => setIndexExpanded(event.currentTarget.open)}><summary>In this history · {events.length} entries</summary><ol>{events.map((event, index) => <li key={index}><a href={`#research-entry-${index}`}><time>{event.date || "Date unavailable"}</time><span>{event.title || "Untitled research entry"}</span></a></li>)}</ol></details></nav>
        <div className={styles.historyDocument}>{events.map((event, index) => <article className={`${styles.historyEntry} ${hasResearchText(event.detail) ? "" : styles.pendingEntry}`} id={`research-entry-${index}`} key={index}><div className={styles.historyMeta}><time>{event.date || "Date unavailable"}</time><span>{sourceKind(event.tag || event.sources?.[0]?.source_type)}</span></div><h2>{event.title || "Untitled research entry"}</h2>{hasResearchText(event.detail) ? <div className={styles.historyDetail}>{event.detail}</div> : <p className={styles.pendingLabel}>Analysis pending</p>}<SourceLinks sources={event.sources} compact includeDate={false} /></article>)}</div>
      </div><p className={styles.finePrint}>Up to ten persisted research entries, newest first. This is the collected record, rather than an entire company history. Research detail is AI-assisted and should be checked against its original sources.</p>
    </> : <EmptyState title={topic ? "No research matches this topic" : "No research history is available"}>{topic ? "Choose another topic or clear the topic filter to see all research." : "Collected research entries will appear here with their dates, detail and original sources. You can still inspect the latest company brief."}</EmptyState>}</ResourceState>
  </div>
}

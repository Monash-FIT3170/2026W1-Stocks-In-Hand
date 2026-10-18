"use client"

import { useState } from "react"
import { fetchTickerTopics } from "../../lib/api"
import { trendLabel } from "../../lib/contentTopics"
import { useCompanyData } from "./CompanyData"
import { useCompanyResource } from "./useCompanyResource"
import { EmptyState, ResourceState, SourceLinks, displayDate } from "./CompanyPrimitives"
import { recordKind } from "./companyFormat"
import workspace from "./CompanyWorkspace.module.css"
import styles from "./TopicClusters.module.css"

function coverage(topic) {
  const count = Number(topic.recent_count) || 0
  const days = Number(topic.trend_days) || 30
  return `${count} ${count === 1 ? "record" : "records"} in ${days} days`
}

function dateRange(cluster) {
  const first = displayDate(cluster.first_published_at)
  const last = displayDate(cluster.last_published_at)
  return first === last ? last : `${first} – ${last}`
}

function ClusterRecord({ record }) {
  return <li className={styles.record}>
    <div className={styles.recordMeta}><span>{recordKind(record)}</span><time>{record.date || "Date unavailable"}</time><span>{record.method === "llm" ? "AI-assisted" : "Keyword rules"}</span></div>
    <h5>{record.title || "Untitled record"}</h5>
    {record.evidence ? <blockquote className={styles.evidence}>{record.evidence}</blockquote> : <p className={styles.noEvidence}>No supporting passage was recorded for this topic.</p>}
    <SourceLinks sources={record.sources} compact includeDate={false} />
  </li>
}

function Cluster({ cluster }) {
  const records = Array.isArray(cluster.records) ? cluster.records : []
  const hidden = Math.max((Number(cluster.artifact_count) || 0) - records.length, 0)
  return <article className={styles.cluster}>
    <div className={styles.clusterHeading}><h4>{cluster.label || "Untitled development"}</h4><p>{cluster.artifact_count} {cluster.artifact_count === 1 ? "record" : "records"} · {dateRange(cluster)}</p></div>
    <ol className={styles.records}>{records.map((record) => <ClusterRecord key={record.id} record={record} />)}</ol>
    {hidden > 0 && <p className={styles.more}>{hidden} older {hidden === 1 ? "record" : "records"} in this development not shown.</p>}
  </article>
}

export function TopicClusters() {
  const { symbol, isLoading } = useCompanyData()
  const resource = useCompanyResource(fetchTickerTopics, symbol, !isLoading)
  const topics = Array.isArray(resource.data?.topics) ? resource.data.topics : []
  const withClusters = topics.filter((topic) => Array.isArray(topic.clusters) && topic.clusters.length)
  const [selected, setSelected] = useState(null)
  const active = selected || withClusters[0]?.topic
  const windowDays = resource.data?.window_days || 90
  return <section className={styles.section} aria-labelledby="topic-clusters-heading">
    <div className={styles.heading}><h2 id="topic-clusters-heading">Topics and developments</h2><p>What the collected records for {symbol} have discussed over the last {windowDays} days, grouped into the developments behind them.</p></div>
    <ResourceState resource={resource} name="Topics">{withClusters.length ? <>
      <div className={workspace.topicList}>{topics.map((topic) => {
        const clusters = Array.isArray(topic.clusters) ? topic.clusters : []
        return <details className={workspace.topic} key={topic.topic} open={(clusters.length && active === topic.topic) || undefined} onToggle={(event) => { if (event.currentTarget.open) setSelected(topic.topic) }}>
          <summary><h3>{topic.label}</h3><span className={styles[`trend_${topic.trend}`] || styles.trend}>{trendLabel(topic.trend)}</span><span className={workspace.topicCoverage}>{coverage({ ...topic, trend_days: resource.data?.trend_days })}</span><span className={workspace.disclosureMark} aria-hidden="true" /></summary>
          <div className={styles.topicBody}>
            <p className={styles.description}>{topic.description}</p>
            {clusters.length ? clusters.map((cluster) => <Cluster cluster={cluster} key={cluster.id} />) : <p className={styles.noEvidence}>No development under this topic was recorded in this period.</p>}
          </div>
        </details>
      })}</div>
      <p className={workspace.finePrint}>Topics are tagged by AI with keyword rules as a fallback, and records about one development are grouped by their wording and dates. Check each against its original source.</p>
    </> : <EmptyState title="No topics are available yet">Topics appear here once collected records about {symbol} have been analysed and tagged. The research history below is still available.</EmptyState>}</ResourceState>
  </section>
}

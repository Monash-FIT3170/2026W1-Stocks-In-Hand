"use client"

import { useState } from "react"
import { fetchTickerCategorySentiment, fetchTickerPublicDiscussionStatus } from "../../lib/api"
import { useCompanyData } from "./CompanyData"
import { useCompanyResource } from "./useCompanyResource"
import { displayDate, EmptyState, ResourceState, sentimentClass, SourceLinks } from "./CompanyPrimitives"
import { hasResearchText, modelName, percentage } from "./companyFormat"
import styles from "./CompanyWorkspace.module.css"

const topics = [{ key: "revenue", name: "Revenue" }, { key: "strategy", name: "Strategy" }, { key: "risk", name: "Risk" }, { key: "dividend", name: "Dividend" }, { key: "organisational", name: "Organisation" }, { key: "user_discussion", name: "Public discussion" }]

function TopicalResearch({ resource, activeTopic, onSelect }) {
  return <section className={styles.topicalSection} id="topical-research">
    <div className={styles.sectionHeading}><h2>Topical research</h2><p>Analysis with its evidence and coverage kept in view.</p></div>
    <ResourceState resource={resource} name="Topical research">
      <div className={styles.topicList}>{topics.map((topic) => {
        const result = resource.data?.categories?.[topic.key]
        const available = result?.available === true
        const label = available ? result.sentiment_label || result.label || "Not classified" : "Unavailable"
        return <details className={styles.topic} key={topic.key} open={activeTopic === topic.key || undefined} onToggle={(event) => { if (event.currentTarget.open) onSelect(topic.key) }}>
          <summary><h3>{topic.name}</h3><span className={sentimentClass(label)}>{label}</span><span className={styles.topicCoverage}>{result?.sources_count != null ? `${result.sources_count} sources` : "Coverage unavailable"}</span><span className={styles.disclosureMark} aria-hidden="true" /></summary>
          <div className={styles.topicBody}><p>{result?.summary || "No analysis is available for this topic. Review the source records for the material currently collected."}</p>
            <div className={styles.mobileTopicEvidence}><h4>{topic.name} evidence</h4><SourceLinks sources={result?.sources} excerpts={false} /></div>
            <details className={styles.analysisDisclosure}><summary>Analysis details · {percentage(result?.confidence_score)} model confidence</summary><dl className={styles.analysisMetadata}><div><dt>Model confidence</dt><dd>{percentage(result?.confidence_score)}</dd></div><div><dt>Sources covered</dt><dd>{result?.sources_count ?? "Unavailable"}</dd></div><div><dt>Evidence chunks analysed</dt><dd>{result?.chunks_analyzed ?? result?.chunks_used ?? "Unavailable"}</dd></div><div><dt>Analysed</dt><dd>{displayDate(result?.latest_analyzed_at)}</dd></div><div><dt>Model</dt><dd>{modelName(result?.model_used || resource.data?.model_used)}</dd></div></dl></details>
          </div>
        </details>
      })}</div>
      {resource.data?.status && <p className={styles.finePrint}>Analysis coverage: {resource.data.status}. Model confidence describes a classification; it does not indicate expected investment performance.</p>}
    </ResourceState>
  </section>
}

function DiscussionCoverage({ resource }) {
  const data = resource.data
  const counts = data?.counts || {}
  return <section className={styles.section} id="discussion-coverage"><details className={styles.coverageDisclosure}><summary><h2>Public discussion coverage</h2><span>{data?.status || (resource.error ? "Could not load" : "Loading")}</span><span className={styles.disclosureMark} aria-hidden="true" /></summary><ResourceState resource={resource} name="Public discussion coverage"><div className={styles.coverageBody}><p>Public discussion is collected separately from company filings and publisher news. Collection status is not a measure of market sentiment.</p><dl className={styles.coverageNumbers}>{["total", "completed", "pending", "queued", "analyzing", "failed"].map((key) => <div key={key}><dt>{key === "analyzing" ? "Analysing" : key[0].toUpperCase() + key.slice(1)}</dt><dd>{counts[key] ?? "Unavailable"}</dd></div>)}</dl><p className={styles.muted}>Latest collection: {displayDate(data?.latest_collected_at)}</p>{Object.keys(data?.sources || {}).length ? <ul className={styles.sourceCounts}>{Object.entries(data.sources).map(([name, count]) => <li key={name}><span>{name}</span><strong>{count}</strong></li>)}</ul> : <p className={styles.muted}>No public-discussion sources are currently reported.</p>}</div></ResourceState></details></section>
}


export function ResearchSummary() {
  const company = useCompanyData()
  const { symbol, aside } = company
  const overview = company.overview || {}
  const categories = useCompanyResource(fetchTickerCategorySentiment, symbol, !company.isLoading)
  const discussion = useCompanyResource(fetchTickerPublicDiscussionStatus, symbol, !company.isLoading)
  const [selectedTopic, setSelectedTopic] = useState(null)
  const activeTopic = selectedTopic || topics.find((topic) => categories.data?.categories?.[topic.key]?.available)?.key
  const activeResult = categories.data?.categories?.[activeTopic]
  const activeName = topics.find((topic) => topic.key === activeTopic)?.name
  const clarity = overview.clarity
  const numbers = aside?.key_numbers || []
  return <div className={styles.summaryDocument}>
    <header className={styles.pageHeading}><h1>Research summary</h1><p>The latest stored research for {overview.company_name || symbol}, with the evidence kept close.</p></header>
    <div className={styles.summaryLayout}>
      <div className={styles.summaryReading}>
        {hasResearchText(overview.story) ? <section className={styles.overviewSection} id="company-overview"><h2>Latest filing brief</h2><p className={styles.lead}>{overview.story}</p><div className={styles.overviewAttribution}><span>AI-assisted brief</span><span>{overview.sources_count != null ? `${overview.sources_count} linked ${overview.sources_count === 1 ? "source" : "sources"}` : "Source count unavailable"}</span></div><SourceLinks sources={overview.sources} compact /></section> : <div className={styles.pendingOverview} id="company-overview"><div><strong>Latest filing</strong><span>Summary pending</span></div><SourceLinks sources={overview.sources} compact includeDate={false} /></div>}
        <TopicalResearch resource={categories} activeTopic={activeTopic} onSelect={setSelectedTopic} />
      </div>
      <aside className={styles.summaryEvidence} aria-label="Research evidence and filing context">
        <section className={styles.evidencePanel}><div className={styles.sectionHeading}><h2>{activeName ? `${activeName} evidence` : "Latest filing material"}</h2><p>{activeResult?.sources_count != null ? `${activeResult.sources_count} sources reported for this analysis.` : "The original material behind the research."}</p></div><SourceLinks sources={activeResult?.sources || overview.sources} excerpts={false} /><p className={styles.finePrint}>Original material remains the authority for each record.</p></section>
        <section className={styles.contextPanel}><h2>Filing details</h2>{numbers.length ? <dl className={styles.numberLedger}>{numbers.map((item, index) => <div key={`${item.label}-${index}`}><dt>{item.label}</dt><dd>{item.value || "N/A"}</dd></div>)}</dl> : <p className={styles.muted}>Filing details are unavailable.</p>}</section>
        <section className={styles.contextPanel}><h2>Latest filing signal</h2><dl className={styles.signalLedger}><div><dt>Classification</dt><dd className={sentimentClass(overview.sentiment_label)}>{overview.sentiment_status === "available" ? overview.sentiment_label : "Unavailable"}</dd></div><div><dt>Model confidence</dt><dd>{overview.latest_signal_confidence_pct ?? "Unavailable"}</dd></div><div><dt>Analysed</dt><dd>{displayDate(overview.latest_signal_analyzed_at)}</dd></div><div><dt>Model</dt><dd>{modelName(overview.latest_signal_model)}</dd></div></dl><p className={styles.finePrint}>The latest filing classification, separate from public discussion.</p></section>
        <section className={styles.contextPanel}><h2>Filing activity themes</h2>{aside?.themes?.length ? <ul className={styles.themeList}>{aside.themes.map((theme, index) => <li key={index}>{theme}</li>)}</ul> : <p className={styles.muted}>No filing activity themes are available.</p>}<p className={styles.finePrint}>Themes describe filing categories, rather than financial conclusions.</p></section>
      </aside>
    </div>
    <section className={`${styles.section} ${styles.factsSection}`} id="research-clarity"><div className={styles.sectionHeading}><h2>Facts & interpretation</h2><p>AI-assisted classification of the stored research.</p></div>{clarity?.is_classified ? <div className={styles.clarityColumns}><div><h3>Confirmed facts</h3>{clarity.confirmed_facts?.length ? <ul>{clarity.confirmed_facts.map((fact, index) => <li key={index}>{fact}</li>)}</ul> : <p>No confirmed facts were returned.</p>}</div><div><h3>Interpretation & speculation</h3>{clarity.speculation?.length ? <ul>{clarity.speculation.map((claim, index) => <li key={index}>{claim}</li>)}</ul> : <p>No interpretation was returned.</p>}</div></div> : <EmptyState title="This research has not been classified">The stored text has not yet been separated into confirmed facts and interpretation. Check its original sources before relying on a claim.</EmptyState>}</section>
    <DiscussionCoverage resource={discussion} />
  </div>
}

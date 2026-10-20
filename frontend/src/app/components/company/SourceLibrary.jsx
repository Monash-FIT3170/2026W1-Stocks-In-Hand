"use client"

import { useMemo, useRef, useState } from "react"
import { fetchTickerNews } from "../../lib/api"
import { useCompanyData } from "./CompanyData"
import { useCompanyResource } from "./useCompanyResource"
import { DocumentIcon, EmptyState, ResourceState, SourceLinks } from "./CompanyPrimitives"
import { filterRecords, hasResearchText, recordKind, selectRecord, publisherLabel } from "./companyFormat"
import styles from "./CompanyWorkspace.module.css"
import { TopicChips } from "../topics/TopicChips"

export function SourceLibrary() {
  const { symbol, isLoading } = useCompanyData()
  const resource = useCompanyResource(fetchTickerNews, symbol, !isLoading)
  const [query, setQuery] = useState("")
  const [kind, setKind] = useState("all")
  const [order, setOrder] = useState("newest")
  const [selectedId, setSelectedId] = useState(null)
  const [choosingRecord, setChoosingRecord] = useState(false)
  const readerRef = useRef(null)
  const searchRef = useRef(null)
  function openReader() {
    setChoosingRecord(false)
    window.requestAnimationFrame(() => {
      readerRef.current?.focus({ preventScroll: true })
      readerRef.current?.scrollIntoView({ behavior: "auto", block: "start" })
    })
  }
  const data = Array.isArray(resource.data) ? resource.data : []
  const records = useMemo(() => filterRecords(data, query, kind, order), [data, query, kind, order])
  const selected = selectRecord(records, selectedId)
  const kinds = [...new Set(data.map(recordKind))]
  const record = selected?.record
  return <div className={styles.library}><span className={styles.visuallyHidden} role="status">{record ? `Selected record: ${record.title}` : "No record selected"}</span>
    <div className={styles.pageHeading}><h1>Source records</h1><p>Inspect the material behind {symbol} research.</p></div>
    <ResourceState resource={resource} name="Source records">{data.length ? <>
      <div className={styles.libraryTools}><label className={styles.searchControl}><span>Search records</span><input aria-label="Search records" ref={searchRef} value={query} onChange={(event) => { setQuery(event.target.value); setChoosingRecord(true) }} placeholder="Title, source or research context" type="search" /></label><details className={styles.libraryFilters}><summary>Filters & order</summary><div className={styles.filterOptions}><label><span>Source type</span><select value={kind} onChange={(event) => setKind(event.target.value)}><option value="all">All sources</option>{kinds.map((type) => <option key={type}>{type}</option>)}</select></label><label><span>Order</span><select value={order} onChange={(event) => setOrder(event.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label></div></details></div>
      <div className={styles.libraryCount} aria-live="polite"><span>{records.length} of {data.length} collected records</span>{(query || kind !== "all") && <button type="button" onClick={() => { setQuery(""); setKind("all") }}>Clear filters</button>}</div>
      {records.length ? <><div className={styles.mobileSourceSelector}><span>{choosingRecord ? "Choose a source to inspect" : "Reading the selected source"}</span><button type="button" aria-expanded={choosingRecord} aria-controls="source-record-index" onClick={() => { if (choosingRecord) openReader(); else { setChoosingRecord(true); window.requestAnimationFrame(() => searchRef.current?.focus()) } }}>{choosingRecord ? "Back to reader" : "Change record"}</button></div><div className={`${styles.librarySplit} ${choosingRecord ? styles.selectingRecord : ""}`}>
        <div className={styles.recordIndex} id="source-record-index"><ol aria-label="Collected source records">{records.map(({ record: item, id }) => <li key={id}><button type="button" className={selected?.id === id ? styles.selectedRecord : styles.recordButton} aria-pressed={selected?.id === id} aria-controls="source-reader" onClick={() => { setSelectedId(id); if (window.matchMedia("(max-width: 767px)").matches) openReader() }}><div className={styles.recordMeta}><span>{recordKind(item)}</span><time>{item.time || "Date unavailable"}</time></div><strong>{item.title || "Untitled source record"}</strong><span className={styles.recordPublisher}><DocumentIcon />{publisherLabel(item.source_name || item.tag) || "Source unavailable"}</span></button></li>)}</ol><button type="button" className={styles.mobileReaderJump} onClick={openReader}>Read selected record</button></div>
        <article className={styles.sourceReader} id="source-reader" aria-label="Selected source record" tabIndex={-1} ref={readerRef} key={selected.id}><div className={styles.readerMeta}><span>{recordKind(record)}</span><time>{record.time || "Date unavailable"}</time></div><h2>{record.title || "Untitled source record"}</h2><TopicChips item={record} />{record.source_name && <p className={styles.readerPublisher}>{publisherLabel(record.source_name)}</p>}<SourceLinks sources={record.sources} url={record.url} label={record.source_label || "Open original source"} compact />{[["Context", record.about], ["What changed", record.changed], ["Research angle", record.matters]].filter(([, text]) => hasResearchText(text)).map(([title, text]) => <section key={title}><h3>{title}</h3><p>{text}</p></section>)}{[record.about, record.changed, record.matters].some((text) => !hasResearchText(text)) && <p className={styles.compactNote}>Analysis is incomplete for this record. Read the original material for the full details.</p>}<p className={styles.finePrint}>AI-assisted context. The original material remains the authority for this record.</p></article>
      </div></> : <EmptyState title="No records match these filters">Try another search phrase or clear the source-type filter to see the collected material.</EmptyState>}
      <p className={styles.finePrint}>This view contains up to ten persisted records returned by the service. It is not an exhaustive archive.</p>
    </> : <EmptyState title="No source records collected yet">No source records were returned for this company. Check again later for collected filings, publisher news and public discussion.</EmptyState>}</ResourceState>
  </div>
}

"use client"

import { useState } from "react"
import { CitationLinks } from "./CitationLinks"
import styles from "../../page.module.css"

export function DeepDiveTimeline({ timeline }) {
  const [activeFilter, setActiveFilter] = useState("All")

  const tags = ["All", ...Array.from(new Set(timeline.map((item) => item.tag).filter(Boolean)))]

  const filtered =
    activeFilter === "All" ? timeline : timeline.filter((item) => item.tag === activeFilter)

  return (
    <div className={styles.timelineShell}>
      <div className={styles.filterTabs}>
        {tags.map((label) => (
          <button
            className={label === activeFilter ? styles.selectedChip : ""}
            key={label}
            onClick={() => setActiveFilter(label)}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
      <div className={styles.timeline}>
        {filtered.length === 0 ? (
          <p className={styles.emptyCard}>No announcements match this filter.</p>
        ) : null}
        {filtered.map((item) => (
          <article className={styles.timelineItem} key={`${item.title}-${item.date}`}>
            <span className={`${styles.timelineDot} ${styles[item.tone]}`} />
            <div className={styles.timelineMonth}>{item.month}</div>
            <div className={styles.timelineCard}>
              <div className={styles.timelineTop}>
                <span className={styles.softPill}>{item.tag}</span>
                <strong>{item.date}</strong>
              </div>
              <h2>{item.title}</h2>
              {item.metrics && item.metrics.length > 0 && (
                <div className={styles.metricGrid}>
                  {item.metrics.map((metric) => <span key={metric}>{metric}</span>)}
                </div>
              )}
              <p>{item.detail}</p>
              <CitationLinks sources={item.sources} />
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}

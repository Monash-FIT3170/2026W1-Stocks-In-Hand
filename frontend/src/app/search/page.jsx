"use client"

import Link from "next/link"
import { useState } from "react"
import { AppFrame } from "../components/layout/AppFrame"
import { SearchIcon } from "../components/icons"
import { searchResults } from "../mock/stocks"
import styles from "../page.module.css"

export default function SearchPage({ searchParams }) {
  const query = searchParams?.q || "BHP"
  const [value, setValue] = useState(query)

  function handleSearch(event) {
    event.preventDefault()
    window.location.href = `/search?q=${encodeURIComponent(value.trim() || "BHP")}`
  }

  return (
    <AppFrame active="home">
      <section className={styles.contentPage}>
        <form className={styles.pageSearchBar} onSubmit={handleSearch}>
          <SearchIcon />
          <input aria-label="Search company or ticker" value={value} onChange={(event) => setValue(event.target.value)} />
        </form>
        <div className={styles.searchHeader}>
          <h1>Search results for <span>&quot;{query.toUpperCase()}&quot;</span></h1>
          <p>We found 3 companies matching your search.</p>
        </div>
        <div className={styles.resultsStack}>
          {searchResults.map((result) => (
            <Link className={`${styles.resultCard} ${styles[result.accent]}`} key={result.name} href="/ticker/BHP">
              <div className={styles.resultContent}>
                <div className={styles.resultMeta}><span>{result.ticker}</span><strong>{result.sector}</strong></div>
                <h2>{result.name}</h2>
                <p>{result.description}</p>
                <div className={styles.resultStats}>
                  <div><span>Price</span><strong>{result.price}</strong></div>
                  <div><span>Sentiment</span><strong className={result.sentiment === "Uncertain" ? styles.warningText : styles.positiveText}>{result.sentiment === "Uncertain" ? "->" : "~"} {result.sentiment}</strong></div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </section>
    </AppFrame>
  )
}

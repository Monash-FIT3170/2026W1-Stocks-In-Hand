"use client"

import Link from "next/link"
import { Suspense, useEffect, useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { SearchIcon } from "../components/icons"
import { fetchTickers } from "../lib/api"
import styles from "../page.module.css"

function formatMarketCap(value) {
  if (!value) {
    return "N/A"
  }

  const amount = Number(value)
  if (!Number.isFinite(amount)) {
    return "N/A"
  }

  if (amount >= 1_000_000_000) {
    return `$${(amount / 1_000_000_000).toFixed(1)}B`
  }

  return `$${amount.toLocaleString()}`
}

function matchesQuery(ticker, query) {
  const search = query.trim().toLowerCase()
  if (!search) {
    return true
  }

  return [ticker.symbol, ticker.company_name, ticker.sector, ticker.industry]
    .filter(Boolean)
    .some((value) => value.toLowerCase().includes(search))
}

function normalizeTickers(data) {
  if (Array.isArray(data)) {
    return data
  }

  if (Array.isArray(data?.tickers)) {
    return data.tickers
  }

  return []
}

function SearchContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const routeQuery = searchParams.get("q")?.trim() || ""
  const [query, setQuery] = useState(routeQuery)
  const [value, setValue] = useState(query)
  const [tickers, setTickers] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState("")
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function loadTickers() {
      setIsLoading(true)
      setError("")

      try {
        const data = await fetchTickers({ limit: 100 })
        const nextTickers = normalizeTickers(data)
        if (!cancelled) {
          setTickers(nextTickers)
          if (nextTickers.length === 0) {
            setError("No companies were returned by the database.")
          }
        }
      } catch {
        if (!cancelled) {
          setError("Company search is unavailable right now. Check your connection and try again.")
          setTickers([])
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    loadTickers()

    return () => {
      cancelled = true
    }
  }, [attempt])

  useEffect(() => {
    setQuery(routeQuery)
    setValue(routeQuery)
  }, [routeQuery])

  const results = useMemo(
    () => normalizeTickers(tickers).filter((ticker) => matchesQuery(ticker, query)),
    [tickers, query]
  )

  function handleSearch(event) {
    event.preventDefault()
    const nextQuery = value.trim()
    setQuery(nextQuery)
    router.push(nextQuery ? `/search?q=${encodeURIComponent(nextQuery)}` : "/search")
  }

  return (
    <section className={styles.contentPage}>
        <form className={styles.pageSearchBar} onSubmit={handleSearch}>
          <SearchIcon />
          <input aria-label="Search company or ticker" value={value} onChange={(event) => setValue(event.target.value)} />
        </form>
        <div className={styles.searchHeader}>
          <h1>{query ? <>Search results for <span>&quot;{query.toUpperCase()}&quot;</span></> : "Browse ASX companies"}</h1>
          <p>{isLoading
            ? "Loading companies from the database."
            : error
              ? "Company results could not be retrieved."
              : `${results.length} ${results.length === 1 ? "company" : "companies"} ${query ? "matched your search" : "available"}.`}</p>
        </div>
        {error ? (
          <div className={styles.emptyCard} role="alert">
            <h2>Could not load company search</h2>
            <p>{error}</p>
            <button className={styles.secondaryButton} onClick={() => setAttempt((value) => value + 1)} type="button">Try again</button>
          </div>
        ) : null}
        <div className={styles.resultsStack}>
          {results.map((result) => (
            <Link className={styles.resultCard} key={result.id} href={`/ticker/${result.symbol}`}>
              <div className={styles.resultContent}>
                <div className={styles.resultMeta}><span>{result.symbol}</span><strong>{result.sector || result.exchange}</strong></div>
                <h2>{result.company_name}</h2>
                <p>{result.industry || "Company profile loaded from the StonksInHand database."}</p>
                <div className={styles.resultStats}>
                  <div><span>Exchange</span><strong>{result.exchange}</strong></div>
                  <div><span>Market cap</span><strong>{formatMarketCap(result.market_cap)}</strong></div>
                </div>
              </div>
            </Link>
          ))}
          {!isLoading && !error && results.length === 0 ? (
            <div className={styles.emptyCard}>
              <h2>No matching companies</h2>
              <p>Try a ticker such as CBA or a broader company name.</p>
            </div>
          ) : null}
        </div>
    </section>
  )
}

export default function SearchPage() {
  return (
    <Suspense fallback={<section className={styles.contentPage}><div className={styles.emptyCard}><p>Loading company search…</p></div></section>}>
      <SearchContent />
    </Suspense>
  )
}

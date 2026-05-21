"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { AppFrame } from "../components/layout/AppFrame"
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

export default function SearchPage() {
  const router = useRouter()
  const [query, setQuery] = useState("BHP")
  const [value, setValue] = useState(query)
  const [tickers, setTickers] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState("")

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
      } catch (err) {
        if (!cancelled) {
          setError(err.message)
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
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const nextQuery = params.get("q") || "BHP"
    setQuery(nextQuery)
    setValue(nextQuery)
  }, [])

  const results = useMemo(
    () => normalizeTickers(tickers).filter((ticker) => matchesQuery(ticker, query)),
    [tickers, query]
  )

  function handleSearch(event) {
    event.preventDefault()
    const nextQuery = value.trim() || "BHP"
    setQuery(nextQuery)
    router.push(`/search?q=${encodeURIComponent(nextQuery)}`)
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
          <p>{isLoading ? "Loading companies from the database." : `We found ${results.length} companies matching your search.`}</p>
        </div>
        {error ? <p className={styles.authError}>{error}</p> : null}
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
          {!isLoading && results.length === 0 ? <p>No matching companies are currently in the database.</p> : null}
        </div>
      </section>
    </AppFrame>
  )
}

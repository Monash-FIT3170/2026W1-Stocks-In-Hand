"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { CloseIcon, PlusIcon } from "../components/icons"
import {
  addWatchlistTicker,
  createWatchlist,
  fetchCurrentInvestor,
  fetchJson,
  fetchWatchlistSummary,
  removeWatchlistTicker,
} from "../lib/api"
import { watchlistCard } from "../lib/watchlists"
import styles from "../page.module.css"

export default function WatchlistRoute() {
  const router = useRouter()
  const [state, setState] = useState({
    error: "",
    investor: null,
    investorId: null,
    isLoading: true,
    companies: [],
    watchlist: null,
  })
  const [isAddOpen, setIsAddOpen] = useState(false)
  const [availableTickers, setAvailableTickers] = useState([])
  const [tickerQuery, setTickerQuery] = useState("")
  const [addError, setAddError] = useState("")
  const [isTickerListLoading, setIsTickerListLoading] = useState(false)
  const [addingTickerId, setAddingTickerId] = useState(null)
  const modalRef = useRef(null)
  const modalTriggerRef = useRef(null)

  const loadWatchlist = useCallback(async ({ showLoading = false } = {}) => {
    if (showLoading) {
      setState((current) => ({ ...current, error: "", isLoading: true }))
    }

    try {
      const investor = await fetchCurrentInvestor()
      const investorId = investor?.id

      if (!investorId) {
        setState((current) => ({ ...current, error: "", isLoading: true }))
        router.replace("/sign-in?next=/watchlist")
        return
      }

      const summary = await fetchWatchlistSummary()

      setState({
        error: "",
        investor,
        investorId,
        isLoading: false,
        companies: summary.companies,
        watchlist: summary.watchlist,
      })
    } catch {
      setState((current) => ({
        ...current,
        error: "Your watchlist is unavailable right now. Check your connection and try again.",
        isLoading: false,
      }))
    }
  }, [router])

  useEffect(() => {
    let isMounted = true
    loadWatchlist({ showLoading: true }).catch(() => {
      if (isMounted) {
        setState((current) => ({
          ...current,
          error: "Your watchlist is unavailable right now. Check your connection and try again.",
          isLoading: false,
        }))
      }
    })
    return () => {
      isMounted = false
    }
  }, [loadWatchlist])

  const watchedTickerIds = useMemo(
    () => new Set(state.companies.map((company) => company.ticker_id)),
    [state.companies]
  )

  const filteredAvailableTickers = useMemo(() => {
    const query = tickerQuery.trim().toLowerCase()
    return (Array.isArray(availableTickers) ? availableTickers : [])
      .filter((ticker) => {
        if (!query) return true
        return (
          ticker.symbol.toLowerCase().includes(query) ||
          ticker.company_name.toLowerCase().includes(query)
        )
      })
      .slice(0, 20)
  }, [availableTickers, tickerQuery])

  async function openAddCompany() {
    if (!state.investorId) return
    modalTriggerRef.current = document.activeElement
    setIsAddOpen(true)
    setAddError("")
    if (availableTickers.length) return

    setIsTickerListLoading(true)
    try {
      const result = await fetchJson("/tickers/?limit=500")
      setAvailableTickers(Array.isArray(result) ? result : [])
    } catch {
      setAddError("Companies could not be loaded. Check your connection and try again.")
    } finally {
      setIsTickerListLoading(false)
    }
  }

  function closeAddCompany() {
    setIsAddOpen(false)
    setTickerQuery("")
    setAddError("")
    setAddingTickerId(null)
  }

  useEffect(() => {
    if (!isAddOpen || !modalRef.current) return undefined

    const modal = modalRef.current
    const selector = "button:not([disabled]), input:not([disabled]), a[href], select:not([disabled]), textarea:not([disabled])"
    const focusable = Array.from(modal.querySelectorAll(selector))
    focusable[0]?.focus()

    function handleDialogKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault()
        closeAddCompany()
        return
      }
      if (event.key !== "Tab" || focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener("keydown", handleDialogKeyDown)
    return () => {
      document.removeEventListener("keydown", handleDialogKeyDown)
      modalTriggerRef.current?.focus()
    }
  }, [isAddOpen])

  async function ensureWatchlist() {
    if (state.watchlist) {
      return state.watchlist
    }
    if (!state.investorId) {
      throw new Error("Could not identify the signed-in investor.")
    }

    const watchlist = await createWatchlist(state.investorId)
    setState((current) => ({ ...current, watchlist }))
    return watchlist
  }

  async function addCompany(ticker) {
    setAddError("")
    setAddingTickerId(ticker.id)

    try {
      const watchlist = await ensureWatchlist()
      await addWatchlistTicker(watchlist.id, ticker.id)
      await loadWatchlist()
      closeAddCompany()
    } catch (err) {
      setAddError(err.message)
      setAddingTickerId(null)
    }
  }

  async function removeCompany(company) {
    if (!state.watchlist) return
    setState((current) => ({
      ...current,
      companies: current.companies.filter((watched) => watched.ticker_id !== company.ticker_id),
    }))
    try {
      await removeWatchlistTicker(state.watchlist.id, company.ticker_id)
    } catch {
      await loadWatchlist()
    }
  }

  const investorName = state.investor?.username || state.investor?.email

  return (
    <section className={styles.contentPage}>
        <div className={styles.watchlistHero}>
          <div>
            <h1>My watchlist</h1>
            <p>{investorName ? `Monitoring ${investorName}'s saved ASX companies.` : "Sign in to view your watchlist."}</p>
            <h2>Saved companies</h2>
          </div>
          <button className={styles.primaryAction} disabled={!state.investorId || state.isLoading} onClick={openAddCompany} type="button">
            <PlusIcon /> Add company
          </button>
        </div>
        <div className={styles.watchlistLayout}>
          <section>
            <div className={styles.watchlistCount}>
              {state.isLoading
                ? "Loading watchlist"
                : `${state.companies.length} saved ${state.companies.length === 1 ? "company" : "companies"}`}
            </div>
            <div className={styles.watchGrid}>
              {state.isLoading && (
                <article className={styles.emptyCard}>
                  <h3>Loading watchlist</h3>
                  <p>Fetching your saved companies</p>
                </article>
              )}
              {state.error && (
                <article className={styles.emptyCard} role="alert">
                  <h3>Could not load watchlist</h3>
                  <p>{state.error}</p>
                  <button className={styles.secondaryButton} onClick={() => loadWatchlist({ showLoading: true })} type="button">Try again</button>
                </article>
              )}
              {!state.isLoading && !state.error && state.companies.map((company) => {
                const card = watchlistCard(company)

                return (
                  <article className={styles.stockCard} key={company.ticker_id}>
                    <Link className={styles.stockCardLink} href={`/ticker/${company.symbol}`}>
                      <div className={styles.stockTop}>
                        <div className={`${styles.stockAvatar} ${styles[card.tone]}`}>{company.symbol[0]}</div>
                        <div>
                          <h3>{company.company_name}</h3>
                          <p>{company.exchange}: {company.symbol}</p>
                        </div>
                      </div>
                      <div className={`${styles.stockStatus} ${styles[card.tone]}`}>
                        <span /> {card.status}
                      </div>
                      {card.brief && <p className={styles.stockBrief}>{card.brief}</p>}
                      <div className={styles.stockFooter}>
                        <span>Last brief: {card.lastBrief}</span>
                        <strong>&gt;</strong>
                      </div>
                    </Link>
                    <button
                      aria-label={`Remove ${company.symbol} from watchlist`}
                      className={styles.stockRemove}
                      onClick={() => removeCompany(company)}
                      type="button"
                    >
                      <CloseIcon />
                    </button>
                  </article>
                )
              })}
              {!state.isLoading && !state.error && !state.companies.length && (
                <article className={styles.emptyCard}>
                  <h3>No companies yet</h3>
                  <p>Add a company to start your watchlist.</p>
                </article>
              )}
            </div>
          </section>
        </div>

        {isAddOpen && (
          <div className={styles.watchlistModalBackdrop} onMouseDown={(event) => event.target === event.currentTarget && closeAddCompany()} role="presentation">
            <section
              aria-describedby="add-company-description"
              aria-labelledby="add-company-title"
              aria-modal="true"
              className={styles.watchlistModal}
              ref={modalRef}
              role="dialog"
            >
              <div className={styles.watchlistModalHeader}>
                <div>
                  <h2 id="add-company-title">Add Company</h2>
                  <p id="add-company-description">Select an ASX company to monitor in your watchlist.</p>
                </div>
                <button aria-label="Close add company" onClick={closeAddCompany} type="button"><CloseIcon /></button>
              </div>
              <label className={styles.watchlistSearch}>
                <span>Search companies</span>
                <input
                  autoFocus
                  onChange={(event) => setTickerQuery(event.target.value)}
                  placeholder="Search by ticker or company"
                  type="search"
                  value={tickerQuery}
                />
              </label>
              {addError && <p aria-live="assertive" className={styles.watchlistModalError} role="alert">{addError}</p>}
              <div className={styles.watchlistTickerList}>
                {isTickerListLoading && <p>Loading companies…</p>}
                {!isTickerListLoading && filteredAvailableTickers.map((ticker) => {
                  const alreadyAdded = watchedTickerIds.has(ticker.id)
                  return (
                    <button
                      className={styles.watchlistTickerOption}
                      disabled={alreadyAdded || addingTickerId === ticker.id}
                      key={ticker.id}
                      onClick={() => addCompany(ticker)}
                      type="button"
                    >
                      <span><strong>{ticker.symbol}</strong>{ticker.company_name}</span>
                      <small>{alreadyAdded ? "Added" : addingTickerId === ticker.id ? "Adding…" : ticker.exchange}</small>
                    </button>
                  )
                })}
              </div>
            </section>
          </div>
        )}
    </section>
  )
}

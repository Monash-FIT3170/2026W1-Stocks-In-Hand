"use client"

import { createContext, useContext, useEffect, useMemo, useState } from "react"
import { usePathname } from "next/navigation"
import { fetchTickerBrief } from "../../lib/api"
import pageStyles from "../../page.module.css"
import styles from "../research/ResearchSurface.module.css"
import { BriefAside } from "./BriefAside"
import { BriefTabs } from "./BriefTabs"
import { TickerHeader } from "./TickerHeader"

const TickerBriefContext = createContext(null)

export function useTickerBrief() {
  const context = useContext(TickerBriefContext)
  if (!context) {
    throw new Error("useTickerBrief must be used inside TickerBriefShell")
  }
  return context
}

export function TickerBriefShell({ children, symbol }) {
  const pathname = usePathname() || ""
  const normalizedPathname = pathname.replace(/\/+$/, "")
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState({ aside: null, error: "", isLoading: true, overview: null })

  useEffect(() => {
    let cancelled = false
    setState((current) => ({ ...current, error: "", isLoading: true }))

    fetchTickerBrief(symbol)
      .then((brief) => {
        if (!cancelled) {
          setState({ aside: brief.aside, error: "", isLoading: false, overview: brief.overview })
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({
            aside: null,
            error: "Ticker details are unavailable right now. Check your connection and try again.",
            isLoading: false,
            overview: null,
          })
        }
      })

    return () => {
      cancelled = true
    }
  }, [attempt, symbol])

  const active = normalizedPathname.endsWith("/news")
    ? "news"
    : normalizedPathname.endsWith("/deep-dive")
      ? "deep"
      : "summary"
  const context = useMemo(
    () => ({ ...state, retry: () => setAttempt((value) => value + 1), symbol }),
    [state, symbol]
  )

  return (
    <TickerBriefContext.Provider value={context}>
      <section className={`${pageStyles.contentPage} ${styles.surface} ${styles.tickerWorkspace}`} aria-busy={state.isLoading}>
        {state.overview ? (
          <TickerHeader data={state.overview} />
        ) : state.isLoading ? (
          <div className={pageStyles.tickerHeaderSkeleton} aria-label={`Loading ${symbol} company details`} />
        ) : (
          <div className={styles.tickerFallback}>
            <p>ASX ticker</p>
            <h1>{symbol}</h1>
            <p>Company details are temporarily unavailable.</p>
          </div>
        )}
        <BriefTabs active={active} symbol={symbol} />
        <div className={styles.briefLayout}>
          <main className={styles.briefMain}>
            {state.error ? (
              <div className={styles.statePanel} role="alert">
                <h2>Some {symbol} details could not be loaded</h2>
                <p>{state.error}</p>
                <button className={styles.secondaryButton} onClick={context.retry} type="button">Try again</button>
              </div>
            ) : null}
            {children}
          </main>
          {state.aside ? (
            <BriefAside data={state.aside} />
          ) : state.isLoading ? (
            <aside className={pageStyles.asideSkeleton} aria-label="Loading ticker details" />
          ) : (
            <aside className={styles.asideUnavailable} aria-label="Ticker details unavailable">
              <h2>Key details unavailable</h2>
              <p>Price, filing metrics, and themes could not be retrieved.</p>
            </aside>
          )}
        </div>
      </section>
    </TickerBriefContext.Provider>
  )
}

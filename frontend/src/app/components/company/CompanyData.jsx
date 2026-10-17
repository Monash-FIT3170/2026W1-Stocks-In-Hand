"use client"

import { createContext, useContext, useEffect, useMemo, useState } from "react"
import { fetchTickerBrief } from "../../lib/api"

const CompanyContext = createContext(null)

// Data boundary only: intentionally defines no presentation or layout.
export function CompanyData({ children, symbol }) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState({ overview: null, aside: null, isLoading: true, error: "" })
  useEffect(() => {
    let cancelled = false
    setState({ overview: null, aside: null, isLoading: true, error: "" })
    fetchTickerBrief(symbol).then((brief) => {
      if (!cancelled) setState({ ...brief, isLoading: false, error: "" })
    }).catch((error) => {
      if (!cancelled) setState({ overview: null, aside: null, isLoading: false, error: error.message || "Company data could not be loaded." })
    })
    return () => { cancelled = true }
  }, [symbol, attempt])
  const value = useMemo(() => ({ ...state, symbol, retry: () => setAttempt((current) => current + 1) }), [state, symbol])
  return <CompanyContext.Provider value={value}>{children}</CompanyContext.Provider>
}

export function useCompanyData() {
  const value = useContext(CompanyContext)
  if (!value) throw new Error("useCompanyData requires CompanyData")
  return value
}

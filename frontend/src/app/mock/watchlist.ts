import { WatchlistStock } from "../types"

export const watchlistStocks: WatchlistStock[] = [
  { ticker: "BHP", name: "BHP Group", status: "Bullish Sentiment", color: "green", alerts: 2 },
  { ticker: "CSL", name: "CSL Limited", status: "Mixed Sentiment", color: "orange", alerts: 0 },
  { ticker: "CBA", name: "CBA", status: "High Conviction", color: "green", alerts: 0 },
]

export const watchAlerts = [
  "BHP released a new ASX announcement - Production Update",
  "CSL sentiment shifted from Positive to Mixed in the last 24 hours",
  "New theme detected for FMG: Regulatory Risk",
  "Weekly AI Digest is ready. Your watchlist shows a net sentiment score of +12%.",
]

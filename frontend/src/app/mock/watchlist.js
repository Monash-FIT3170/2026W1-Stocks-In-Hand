// Placeholder watchlist and alert data.
// Later this should come from the signed-in user's watchlist and notification history.
// color maps to CSS classes used by stock avatars/status dots; alerts is just a badge
// count for the mock card and does not represent a real notification model yet.
export const watchlistStocks = [
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

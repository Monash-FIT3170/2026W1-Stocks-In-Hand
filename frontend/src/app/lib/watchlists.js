const DAY_MS = 86_400_000
const BRIEF_LENGTH = 150
const SIGNAL_TONES = { positive: "green", negative: "red" }

export function buildWatchlistCreatePayload(investorId) {
  if (!investorId) {
    throw new Error("Could not identify the signed-in investor.")
  }

  return {
    investor_id: investorId,
    name: "My Watchlist",
  }
}

function titleCase(value) {
  return value.replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
}

function relativeDate(value, now) {
  const date = value ? new Date(value) : null
  if (!date || Number.isNaN(date.getTime())) {
    return "Not available"
  }
  const days = Math.floor((now.getTime() - date.getTime()) / DAY_MS)
  if (days <= 0) return "Today"
  if (days === 1) return "Yesterday"
  return `${days} days ago`
}

// How one company of GET /watchlists/me/summary appears on the watchlist page.
export function watchlistCard(company, now = new Date()) {
  const label = company.latest_signal?.sentiment_label?.replace(/[_-]/g, " ").trim().toLowerCase()
  const brief = typeof company.brief === "string" && company.brief ? company.brief : null
  return {
    status: label ? `${titleCase(label)} Sentiment` : company.sector ? `${company.sector} Monitoring` : "Monitoring",
    tone: SIGNAL_TONES[label] || "orange",
    brief: brief && brief.length > BRIEF_LENGTH ? `${brief.slice(0, BRIEF_LENGTH - 3)}…` : brief,
    lastBrief: relativeDate(company.last_brief_at, now),
  }
}

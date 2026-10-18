// The content topics the backend tags records with: app/content_topic_vocabulary.py
// and parsing/content_topics/taxonomy.py. The identifiers must match them.
export const CONTENT_TOPICS = [
  { id: "earnings_guidance", label: "Earnings and guidance", short: "Earnings" },
  { id: "litigation", label: "Litigation", short: "Litigation" },
  { id: "regulation", label: "Regulation", short: "Regulation" },
  { id: "product_launch", label: "Product launches", short: "Product launch" },
  { id: "macro_exposure", label: "Macro-economic exposure", short: "Macro" },
]

const BY_ID = new Map(CONTENT_TOPICS.map((topic) => [topic.id, topic]))

const TRENDS = {
  new: "New this month",
  rising: "Rising",
  steady: "Steady",
  falling: "Falling",
  quiet: "No recent coverage",
}

export function isContentTopic(value) {
  return BY_ID.has(value)
}

// The topic's display label; an identifier the frontend does not know yet is
// shown as its words instead of being hidden.
export function topicLabel(value, { short = false } = {}) {
  const topic = BY_ID.get(value)
  if (topic) return short ? topic.short : topic.label
  const words = String(value || "").replace(/_/g, " ").trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : ""
}

// A record's topics as the API sent them, without duplicates or blanks, in order.
export function recordTopics(item) {
  const topics = Array.isArray(item?.topics) ? item.topics : []
  return [...new Set(topics.filter((topic) => typeof topic === "string" && topic.trim()))]
}

export function trendLabel(trend) {
  return TRENDS[trend] || "Trend unavailable"
}

export function topicFilterHref(topic) {
  return isContentTopic(topic) ? `/announcements?topic=${encodeURIComponent(topic)}` : "/announcements"
}

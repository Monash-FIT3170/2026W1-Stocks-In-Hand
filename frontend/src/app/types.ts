export type Tone = "green" | "orange" | "red"

export type SearchResult = {
  ticker: string
  sector: string
  name: string
  description: string
  price: string
  sentiment: "Positive" | "Uncertain"
  accent: "green" | "orange"
}

export type Announcement = {
  ticker: string
  tag: string
  time: string
  title: string
  about: string
  changed: string
  matters: string
}

export type TimelineItem = {
  month: string
  tag: string
  title: string
  date: string
  detail: string
  metrics: string[]
  tone: Tone
}

export type WatchlistStock = {
  ticker: string
  name: string
  status: string
  color: "green" | "orange"
  alerts: number
}

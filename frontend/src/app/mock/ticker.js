// Placeholder ticker brief data shared by Summary, News, and Deep Dive screens.
// These values are intentionally static until company/event APIs are introduced.
// marketClaims drives the right sidebar, themes drives the themes panels, and
// timelineItems drives the Deep Dive chronology.
export const marketClaims = {
  confirmed: [
    "Jansen Potash Stage 2 investment approved for $4.9B.",
    "Dividend payout ratio maintained at 50% target.",
  ],
  rumoured: [
    "Potential divestment of certain metallurgical coal assets.",
    "Interest in mid-tier copper producers in Latin America.",
  ],
}

export const themes = [
  "Copper Focus: Growing strategic shift towards electrification metals.",
  "Labor Shortages: Persistent operational pressure in Western Australia mines.",
  "China Stimulus: Direct correlation with iron ore demand sentiment.",
]

export const timelineItems = [
  {
    month: "Aug 2024",
    tag: "Earnings",
    title: "Full Year Earnings Released",
    date: "Aug 27, 2024",
    detail: "BHP has delivered a strong set of results for the 2024 financial year, reflecting the underlying quality of our assets and the exceptional efforts of our people.",
    metrics: ["Revenue $55.7B", "Net Profit $13.4B", "Dividend $1.46/sh"],
    tone: "green",
  },
  {
    month: "Jun 2024",
    tag: "Reported / Unconfirmed",
    title: "Anglo American Acquisition Pursuit Ends",
    date: "Jun 02, 2024",
    detail: "Reports suggest BHP has officially walked away from the $49 billion bid for Anglo American after three failed attempts to reach an agreement on the complex structure of the deal.",
    metrics: ["Market reacted positively to capital discipline stance."],
    tone: "orange",
  },
  {
    month: "May 2024",
    tag: "Legal",
    title: "Samarco Dam Collapse Settlement Update",
    date: "May 15, 2024",
    detail: "Negotiations with Brazilian authorities continue regarding the Samarco dam disaster. Total provision estimate revised to $6.5 Billion.",
    metrics: [],
    tone: "red",
  },
]

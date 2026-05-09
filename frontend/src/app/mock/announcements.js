// Placeholder announcement data for the prototype.
// Keep the shape close to what the UI needs rather than what an API might return:
// ticker/tag/time/title plus the three "plain English" explanation fields.
// When the backend exists, transform API records into this shape before passing
// them into AnnouncementCard so the presentation component stays simple.
export const announcementCards = [
  {
    ticker: "BHP",
    tag: "Earnings/Guidance",
    time: "10:42 AM",
    title: "Quarterly Production Report",
    about: "Comprehensive review of operational performance across iron ore, copper, and metallurgical coal assets for Q3.",
    changed: "Iron ore output up 8% YoY; Copper guidance maintained despite rain disruptions in Chile.",
    matters: "Strong volume growth supports cash flow; reaffirms BHP's position as a low-cost producer in a volatile market.",
  },
  {
    ticker: "CBA",
    tag: "Regulation",
    time: "09:15 AM",
    title: "Notice of Extraordinary General Meeting",
    about: "Meeting regarding the proposed share buy-back program and executive remuneration structural changes.",
    changed: "Proposed $2B share buy-back to return excess capital to shareholders.",
    matters: "Direct impact on EPS and capital management efficiency; signal of balance sheet strength.",
  },
  {
    ticker: "PLS",
    tag: "Macroeconomic",
    time: "08:30 AM",
    title: "Exploration Update - Pilgangoora",
    about: "New drilling results from the central tenement extension identifying high-grade lithium mineralization.",
    changed: "Intercepts confirm strike extension; significant increase in inferred resource potential.",
    matters: "Extends mine life and supports future expansion feasibility studies; bullish for mid-term valuation.",
  },
]

export const trendingStocks = ["TLS", "FMG", "MQG", "WES"]

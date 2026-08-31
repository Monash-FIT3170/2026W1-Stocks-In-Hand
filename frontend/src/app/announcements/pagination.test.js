import { describe, expect, it } from "vitest"

import { appendAnnouncementPage } from "./pagination"


describe("announcement pagination", () => {
  it("deduplicates overlapping pages while advancing by fetched rows", () => {
    const existing = [{ id: "first" }, { id: "overlap" }]
    const incoming = [{ id: "overlap" }, { id: "third" }]

    const result = appendAnnouncementPage(existing, incoming, 2)

    expect(result.announcementCards.map((item) => item.id)).toEqual([
      "first",
      "overlap",
      "third",
    ])
    expect(result.nextOffset).toBe(4)
  })

  it("drops malformed cards without an id", () => {
    const result = appendAnnouncementPage([], [{ title: "Missing id" }], 0)

    expect(result).toEqual({ announcementCards: [], nextOffset: 1 })
  })
})

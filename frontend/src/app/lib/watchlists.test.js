import { describe, expect, it } from "vitest"
import { buildWatchlistCreatePayload } from "./watchlists"

describe("buildWatchlistCreatePayload", () => {
  it("includes the authenticated investor required by the API schema", () => {
    expect(buildWatchlistCreatePayload("investor-123")).toEqual({
      investor_id: "investor-123",
      name: "My Watchlist",
    })
  })

  it("refuses to create an ownerless watchlist", () => {
    expect(() => buildWatchlistCreatePayload(null)).toThrow(
      "Could not identify the signed-in investor."
    )
  })
})

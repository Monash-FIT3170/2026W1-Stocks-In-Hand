export function buildWatchlistCreatePayload(investorId) {
  if (!investorId) {
    throw new Error("Could not identify the signed-in investor.")
  }

  return {
    investor_id: investorId,
    name: "My Watchlist",
  }
}

export function safeSourceUrl(value) {
  if (typeof value !== "string" || /[\u0000-\u001f]/.test(value)) return null
  try {
    const url = new URL(value)
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password
      ? value.trim()
      : null
  } catch {
    return null
  }
}

// Match the displayed wording so stale or fallback summaries cannot borrow evidence.
export function findClaim(claims, field, text) {
  if (!Array.isArray(claims) || typeof text !== "string") return null
  return claims.find((claim) => claim?.field === field && claim.text === text.trim()) || null
}

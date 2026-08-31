/** Merge one fetched page while preserving the API offset independently. */
export function appendAnnouncementPage(currentCards, incomingCards, currentOffset) {
  const seenIds = new Set()
  const announcementCards = []

  for (const item of [...currentCards, ...incomingCards]) {
    if (!item?.id || seenIds.has(item.id)) {
      continue
    }
    seenIds.add(item.id)
    announcementCards.push(item)
  }

  return {
    announcementCards,
    nextOffset: currentOffset + incomingCards.length,
  }
}

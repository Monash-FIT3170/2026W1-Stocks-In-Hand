const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export async function fetchAnnouncements(filters = {}) {
  const params = new URLSearchParams()

  if (filters.today) {
    params.set("today", "true")
  }

  if (filters.sector) {
    params.set("sector", filters.sector)
  }

  const query = params.toString()
  const response = await fetch(`${API_URL}/announcements/${query ? `?${query}` : ""}`, {
    cache: "no-store",
  })

  if (!response.ok) {
    throw new Error("Failed to fetch announcements")
  }

  return response.json()
}

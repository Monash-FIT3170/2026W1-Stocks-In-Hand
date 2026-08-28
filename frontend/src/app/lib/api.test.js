import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

const authMocks = vi.hoisted(() => ({
  getCognitoAccessToken: vi.fn(),
  isCognitoAuthEnabled: vi.fn(),
  signOutFromCognito: vi.fn(),
}))

vi.mock("../../auth/cognito", () => authMocks)

beforeEach(() => {
  vi.clearAllMocks()
  authMocks.getCognitoAccessToken.mockResolvedValue(null)
  authMocks.isCognitoAuthEnabled.mockReturnValue(false)
  authMocks.signOutFromCognito.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("apiFetch authentication compatibility", () => {
  test("keeps legacy and public requests unauthenticated", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    const { apiFetch } = await import("./api")

    await apiFetch("/tickers/")

    const [, options] = fetchMock.mock.calls[0]
    expect(options.headers.has("Authorization")).toBe(false)
  })

  test("adds a Cognito bearer token without changing caller options", async () => {
    authMocks.getCognitoAccessToken.mockResolvedValue("access-token")
    authMocks.isCognitoAuthEnabled.mockReturnValue(true)
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    const { apiFetch } = await import("./api")

    await apiFetch("/auth/me", { method: "GET", credentials: "include" })

    const [, options] = fetchMock.mock.calls[0]
    expect(options.method).toBe("GET")
    expect(options.credentials).toBe("include")
    expect(options.headers.get("Authorization")).toBe("Bearer access-token")
  })

  test("refreshes once after an authenticated 401", async () => {
    authMocks.getCognitoAccessToken
      .mockResolvedValueOnce("expired-token")
      .mockResolvedValueOnce("refreshed-token")
    authMocks.isCognitoAuthEnabled.mockReturnValue(true)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response("{}", { status: 401 }))
      .mockResolvedValueOnce(new Response("{}", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    const { apiFetch } = await import("./api")

    const response = await apiFetch("/auth/me")

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(authMocks.getCognitoAccessToken).toHaveBeenLastCalledWith({ forceRefresh: true })
    expect(fetchMock.mock.calls[1][1].headers.get("Authorization")).toBe(
      "Bearer refreshed-token",
    )
  })

  test("never overwrites an explicit authorization header", async () => {
    authMocks.getCognitoAccessToken.mockResolvedValue("session-token")
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    const { apiFetch } = await import("./api")

    await apiFetch("/diagnostic", {
      headers: { Authorization: "Bearer explicit-token" },
    })

    expect(authMocks.getCognitoAccessToken).not.toHaveBeenCalled()
    expect(fetchMock.mock.calls[0][1].headers.get("Authorization")).toBe(
      "Bearer explicit-token",
    )
  })
})

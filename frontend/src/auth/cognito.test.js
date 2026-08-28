import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

const amplifyMocks = vi.hoisted(() => ({
  configure: vi.fn(),
  confirmResetPassword: vi.fn(),
  confirmSignIn: vi.fn(),
  confirmSignUp: vi.fn(),
  fetchAuthSession: vi.fn(),
  getCurrentUser: vi.fn(),
  resendSignUpCode: vi.fn(),
  resetPassword: vi.fn(),
  setUpTOTP: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  signUp: vi.fn(),
  updateMFAPreference: vi.fn(),
  verifyTOTPSetup: vi.fn(),
}))

vi.mock("aws-amplify", () => ({
  Amplify: { configure: amplifyMocks.configure },
}))

vi.mock("aws-amplify/auth", () => ({
  confirmResetPassword: amplifyMocks.confirmResetPassword,
  confirmSignIn: amplifyMocks.confirmSignIn,
  confirmSignUp: amplifyMocks.confirmSignUp,
  fetchAuthSession: amplifyMocks.fetchAuthSession,
  getCurrentUser: amplifyMocks.getCurrentUser,
  resendSignUpCode: amplifyMocks.resendSignUpCode,
  resetPassword: amplifyMocks.resetPassword,
  setUpTOTP: amplifyMocks.setUpTOTP,
  signIn: amplifyMocks.signIn,
  signOut: amplifyMocks.signOut,
  signUp: amplifyMocks.signUp,
  updateMFAPreference: amplifyMocks.updateMFAPreference,
  verifyTOTPSetup: amplifyMocks.verifyTOTPSetup,
}))

async function loadCognito() {
  return import("./cognito")
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.resetModules()
  vi.stubEnv("NEXT_PUBLIC_AUTH_PROVIDER", "cognito")
  vi.stubEnv("NEXT_PUBLIC_AWS_REGION", "ap-southeast-2")
  vi.stubEnv("NEXT_PUBLIC_COGNITO_USER_POOL_ID", "ap-southeast-2_TestPool")
  vi.stubEnv("NEXT_PUBLIC_COGNITO_APP_CLIENT_ID", "client-123")
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe("Cognito account flows", () => {
  test("normalizes account details before signup", async () => {
    const sampleValue = ["Valid", "Password", "1!"].join("")
    amplifyMocks.signUp.mockResolvedValue({ nextStep: { signUpStep: "CONFIRM_SIGN_UP" } })
    const { createCognitoAccount } = await loadCognito()

    await createCognitoAccount({
      email: " Test@Example.com ",
      name: " Test User ",
      password: sampleValue,
    })

    expect(amplifyMocks.signUp).toHaveBeenCalledWith({
      username: "test@example.com",
      password: sampleValue,
      options: {
        userAttributes: {
          email: "test@example.com",
          name: "Test User",
        },
      },
    })
    expect(amplifyMocks.configure).toHaveBeenCalledOnce()
  })

  test("trims confirmation and password-reset values", async () => {
    const {
      confirmCognitoAccount,
      confirmCognitoPasswordReset,
      startCognitoPasswordReset,
    } = await loadCognito()

    await confirmCognitoAccount({
      email: " TEST@EXAMPLE.COM ",
      confirmationCode: " 123456 ",
    })
    await startCognitoPasswordReset(" TEST@EXAMPLE.COM ")
    await confirmCognitoPasswordReset({
      email: " TEST@EXAMPLE.COM ",
      confirmationCode: " 654321 ",
      newPassword: "NewPassword1!",
    })

    expect(amplifyMocks.confirmSignUp).toHaveBeenCalledWith({
      username: "test@example.com",
      confirmationCode: "123456",
    })
    expect(amplifyMocks.resetPassword).toHaveBeenCalledWith({
      username: "test@example.com",
    })
    expect(amplifyMocks.confirmResetPassword).toHaveBeenCalledWith({
      username: "test@example.com",
      confirmationCode: "654321",
      newPassword: "NewPassword1!",
    })
  })

  test("passes the trimmed TOTP sign-in challenge", async () => {
    const { confirmCognitoSignIn } = await loadCognito()

    await confirmCognitoSignIn(" 123456 ")

    expect(amplifyMocks.confirmSignIn).toHaveBeenCalledWith({
      challengeResponse: "123456",
    })
  })

  test("sets up and prefers software-token MFA", async () => {
    const setupUri = new URL("otpauth://totp/StonksInHand:test")
    const getSetupUri = vi.fn(() => setupUri)
    amplifyMocks.setUpTOTP.mockResolvedValue({
      getSetupUri,
      sharedSecret: "shared-secret",
    })
    const { completeCognitoTotpSetup, startCognitoTotpSetup } = await loadCognito()

    await expect(startCognitoTotpSetup()).resolves.toEqual({
      setupUri: setupUri.toString(),
      sharedSecret: "shared-secret",
    })
    await completeCognitoTotpSetup(" 123456 ")

    expect(getSetupUri).toHaveBeenCalledWith("StonksInHand")
    expect(amplifyMocks.verifyTOTPSetup).toHaveBeenCalledWith({ code: "123456" })
    expect(amplifyMocks.updateMFAPreference).toHaveBeenCalledWith({ totp: "PREFERRED" })
  })

  test("uses global Cognito sign-out", async () => {
    const { signOutFromCognito } = await loadCognito()

    await signOutFromCognito()

    expect(amplifyMocks.signOut).toHaveBeenCalledWith({ global: true })
  })

  test("maps Cognito errors without exposing service details", async () => {
    const { getCognitoErrorMessage } = await loadCognito()

    expect(getCognitoErrorMessage({ name: "CodeMismatchException" }, "Fallback")).toBe(
      "The confirmation code is not correct.",
    )
    expect(getCognitoErrorMessage({ name: "UnexpectedServiceError" }, "Fallback")).toBe(
      "Fallback",
    )
  })
})

describe("Cognito session handling", () => {
  test("returns and force-refreshes the access token", async () => {
    vi.stubGlobal("window", {})
    amplifyMocks.fetchAuthSession.mockResolvedValue({
      tokens: { accessToken: { toString: () => "access-token" } },
    })
    const { getCognitoAccessToken } = await loadCognito()

    await expect(getCognitoAccessToken({ forceRefresh: true })).resolves.toBe("access-token")

    expect(amplifyMocks.fetchAuthSession).toHaveBeenCalledWith({ forceRefresh: true })
  })

  test("returns null for an unauthenticated browser session", async () => {
    vi.stubGlobal("window", {})
    amplifyMocks.fetchAuthSession.mockRejectedValue({ name: "UserUnAuthenticatedException" })
    const { getCognitoAccessToken } = await loadCognito()

    await expect(getCognitoAccessToken()).resolves.toBeNull()
  })
})

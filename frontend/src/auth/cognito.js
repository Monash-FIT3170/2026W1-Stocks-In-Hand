import { Amplify } from "aws-amplify"
import {
  confirmSignIn,
  confirmSignUp,
  confirmResetPassword,
  fetchAuthSession,
  getCurrentUser,
  resendSignUpCode,
  resetPassword,
  setUpTOTP,
  signIn,
  signOut,
  signUp,
  updateMFAPreference,
  verifyTOTPSetup,
} from "aws-amplify/auth"

const AUTH_PROVIDER = process.env.NEXT_PUBLIC_AUTH_PROVIDER || "legacy"
const AWS_REGION = process.env.NEXT_PUBLIC_AWS_REGION || ""
const USER_POOL_ID = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID || ""
const USER_POOL_CLIENT_ID = process.env.NEXT_PUBLIC_COGNITO_APP_CLIENT_ID || ""

if (["dual", "cognito"].includes(AUTH_PROVIDER) && (!AWS_REGION || !USER_POOL_ID || !USER_POOL_CLIENT_ID)) {
  throw new Error("Cognito authentication build values are missing")
}

let isConfigured = false

export function isCognitoAuthEnabled() {
  return AUTH_PROVIDER === "dual" || AUTH_PROVIDER === "cognito"
}

function configureCognito() {
  if (!isCognitoAuthEnabled()) {
    throw new Error("Cognito authentication is not enabled")
  }
  if (!AWS_REGION || !USER_POOL_ID || !USER_POOL_CLIENT_ID) {
    throw new Error("Cognito authentication is not configured")
  }
  if (isConfigured) {
    return
  }

  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: USER_POOL_ID,
        userPoolClientId: USER_POOL_CLIENT_ID,
        loginWith: {
          email: true,
        },
      },
    },
  })
  isConfigured = true
}

export async function createCognitoAccount({ email, name, password }) {
  configureCognito()
  const normalizedEmail = email.trim().toLowerCase()
  return signUp({
    username: normalizedEmail,
    password,
    options: {
      userAttributes: {
        email: normalizedEmail,
        name: name.trim(),
      },
    },
  })
}

export async function confirmCognitoAccount({ email, confirmationCode }) {
  configureCognito()
  return confirmSignUp({
    username: email.trim().toLowerCase(),
    confirmationCode: confirmationCode.trim(),
  })
}

export async function resendCognitoConfirmationCode(email) {
  configureCognito()
  return resendSignUpCode({
    username: email.trim().toLowerCase(),
  })
}

export async function signInWithCognito({ email, password }) {
  configureCognito()
  return signIn({
    username: email.trim().toLowerCase(),
    password,
  })
}

export async function confirmCognitoSignIn(challengeResponse) {
  configureCognito()
  return confirmSignIn({
    challengeResponse: challengeResponse.trim(),
  })
}

export async function startCognitoTotpSetup() {
  configureCognito()
  const details = await setUpTOTP()
  return {
    setupUri: details.getSetupUri("StonksInHand").toString(),
    sharedSecret: details.sharedSecret,
  }
}

export async function completeCognitoTotpSetup(code) {
  configureCognito()
  await verifyTOTPSetup({ code: code.trim() })
  await updateMFAPreference({ totp: "PREFERRED" })
}

export async function signOutFromCognito() {
  configureCognito()
  await signOut({ global: true })
}

export async function getCognitoAccessToken({ forceRefresh = false } = {}) {
  if (!isCognitoAuthEnabled() || typeof window === "undefined") {
    return null
  }

  configureCognito()
  try {
    const session = await fetchAuthSession({ forceRefresh })
    return session.tokens?.accessToken?.toString() || null
  } catch (error) {
    if (error?.name === "UserUnAuthenticatedException") {
      return null
    }
    throw error
  }
}

export async function hasCognitoSession() {
  if (!isCognitoAuthEnabled() || typeof window === "undefined") {
    return false
  }
  configureCognito()
  try {
    await getCurrentUser()
    return Boolean(await getCognitoAccessToken())
  } catch {
    return false
  }
}

export async function startCognitoPasswordReset(email) {
  configureCognito()
  return resetPassword({
    username: email.trim().toLowerCase(),
  })
}

export async function confirmCognitoPasswordReset({
  email,
  confirmationCode,
  newPassword,
}) {
  configureCognito()
  return confirmResetPassword({
    username: email.trim().toLowerCase(),
    confirmationCode: confirmationCode.trim(),
    newPassword,
  })
}

export function getCognitoErrorMessage(error, fallback) {
  const messages = {
    CodeMismatchException: "The confirmation code is not correct.",
    ExpiredCodeException: "The confirmation code has expired.",
    InvalidPasswordException: "Use at least 12 characters with upper and lower case letters, a number, and a symbol.",
    InvalidParameterException: "Check the details and try again.",
    LimitExceededException: "Too many attempts. Wait a few minutes, then try again.",
    EnableSoftwareTokenMFAException: "Could not enable the authenticator. Start setup again.",
    NotAuthorizedException: "The email or password is not correct.",
    SoftwareTokenMFANotFoundException: "Authenticator setup is not available.",
    UserNotConfirmedException: "Confirm your email before signing in.",
    UsernameExistsException: "An account with this email already exists.",
  }
  return messages[error?.name] || fallback
}

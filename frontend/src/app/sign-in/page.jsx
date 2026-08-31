"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { AuthField } from "../components/auth/AuthField"
import { apiFetch } from "../lib/api"
import { friendlyAuthError } from "../lib/authErrors"
import {
  confirmCognitoSignIn,
  getCognitoErrorMessage,
  isCognitoAuthEnabled,
  signInWithCognito,
  signOutFromCognito,
} from "../../auth/cognito"
import styles from "../page.module.css"

const AUTH_STORAGE_KEY = "stonks_signed_in"
const PENDING_EMAIL_KEY = "stonks_pending_email"

function getErrorMessage(data, fallback) {
  if (Array.isArray(data.detail)) {
    return data.detail.map((error) => error.msg).join(", ")
  }

  if (typeof data.detail === "string") {
    return data.detail
  }

  return fallback
}

export default function SignInRoute() {
  const router = useRouter()
  const [form, setForm] = useState({ email: "", password: "" })
  const [mfaCode, setMfaCode] = useState("")
  const [mfaSetup, setMfaSetup] = useState(null)
  const [awaitingMfa, setAwaitingMfa] = useState(false)
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  function updateForm(event) {
    setForm((current) => ({
      ...current,
      [event.target.name]: event.target.value,
    }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError("")
    setIsSubmitting(true)

    try {
      if (isCognitoAuthEnabled()) {
        if (awaitingMfa) {
          const confirmation = await confirmCognitoSignIn(mfaCode)
          if (!confirmation.isSignedIn) {
            throw new Error("The authenticator challenge is not complete.")
          }
          await bootstrapCognitoProfile()
          return
        }

        const result = await signInWithCognito(form)
        if (!result.isSignedIn) {
          const nextStep = result.nextStep?.signInStep
          if (nextStep === "CONFIRM_SIGN_UP") {
            window.sessionStorage.setItem(
              PENDING_EMAIL_KEY,
              form.email.trim().toLowerCase(),
            )
            router.push("/confirm-sign-up")
            return
          }
          if (nextStep === "RESET_PASSWORD") {
            window.sessionStorage.setItem(
              PENDING_EMAIL_KEY,
              form.email.trim().toLowerCase(),
            )
            router.push("/forgot-password")
            return
          }
          if (nextStep === "CONFIRM_SIGN_IN_WITH_TOTP_CODE") {
            setAwaitingMfa(true)
            setMfaSetup(null)
            return
          }
          if (nextStep === "CONTINUE_SIGN_IN_WITH_TOTP_SETUP") {
            const details = result.nextStep?.totpSetupDetails
            setMfaSetup({
              setupUri: details?.getSetupUri?.("StonksInHand")?.toString() || "",
              sharedSecret: details?.sharedSecret || "",
            })
            setAwaitingMfa(true)
            return
          }
          throw new Error("More account setup is required before you can sign in.")
        }

        await bootstrapCognitoProfile()
        return
      }

      const response = await apiFetch("/auth/sign-in", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      })
      const data = await response.json().catch(() => ({}))

      if (!response.ok) {
        throw new Error(friendlyAuthError(getErrorMessage(data, "Could not sign in"), "Could not sign in"))
      }

      window.localStorage.setItem(AUTH_STORAGE_KEY, "true")
      window.dispatchEvent(new Event("stonks-auth-changed"))
      router.push("/watchlist")
    } catch (err) {
      if (err?.name === "UserNotConfirmedException") {
        window.sessionStorage.setItem(
          PENDING_EMAIL_KEY,
          form.email.trim().toLowerCase(),
        )
        router.push("/confirm-sign-up")
        return
      }
      setError(
        err instanceof TypeError
          ? "Could not reach the sign-in service. Check your connection and try again."
          : getCognitoErrorMessage(
              err,
              friendlyAuthError(err.message, "Could not sign in"),
            )
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  async function bootstrapCognitoProfile() {
    const bootstrapResponse = await apiFetch("/auth/bootstrap", {
      method: "POST",
    })
    const bootstrapData = await bootstrapResponse.json().catch(() => ({}))
    if (!bootstrapResponse.ok) {
      await signOutFromCognito().catch(() => {})
      throw new Error(
        friendlyAuthError(
          getErrorMessage(bootstrapData, "Could not load your profile"),
          "Could not load your profile",
        ),
      )
    }
    window.localStorage.setItem(AUTH_STORAGE_KEY, "true")
    window.dispatchEvent(new Event("stonks-auth-changed"))
    router.push("/watchlist")
  }

  return (
    <section className={styles.authPage}>
        <form className={styles.authCard} onSubmit={handleSubmit}>
          <h1>Welcome back</h1>
          <p>Access your saved ASX watchlist and company research.</p>
          {!awaitingMfa ? (
            <>
              <AuthField
                autoComplete="email"
                label="Email address"
                maxLength={320}
                name="email"
                onChange={updateForm}
                placeholder="name@example.com"
                required
                value={form.email}
              />
              <AuthField
                autoComplete="current-password"
                label="Password"
                minLength={1}
                name="password"
                onChange={updateForm}
                placeholder="Enter your password"
                password
                required
                value={form.password}
              />
            </>
          ) : (
            <>
              {mfaSetup?.sharedSecret ? (
                <div className={styles.securityNote}>
                  Add this key to your authenticator app: <code>{mfaSetup.sharedSecret}</code>
                  {mfaSetup.setupUri ? <a href={mfaSetup.setupUri}>Open authenticator app</a> : null}
                </div>
              ) : null}
              <AuthField
                autoComplete="one-time-code"
                label="Authenticator code"
                maxLength={6}
                minLength={6}
                name="mfaCode"
                onChange={(event) => setMfaCode(event.target.value)}
                placeholder="Enter the six-digit code"
                required
                value={mfaCode}
              />
            </>
          )}
          {error ? <p aria-live="assertive" className={styles.authError} role="alert">{error}</p> : null}
          <button className={styles.authSubmit} disabled={isSubmitting} type="submit">
            {isSubmitting ? "Checking…" : awaitingMfa ? "Confirm code" : "Sign In"}
          </button>
          {isCognitoAuthEnabled() ? (
            <span className={styles.authSwap}><Link href="/forgot-password">Forgot your password?</Link></span>
          ) : null}
          <span className={styles.authSwap}>Don&apos;t have an account?<Link href="/sign-up">Sign up</Link></span>
        </form>
    </section>
  )
}

"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { AuthField } from "../components/auth/AuthField"
import {
  confirmCognitoAccount,
  getCognitoErrorMessage,
  resendCognitoConfirmationCode,
} from "../../auth/cognito"
import styles from "../page.module.css"

const PENDING_EMAIL_KEY = "stonks_pending_email"
const RESEND_COOLDOWN_SECONDS = 60

export default function ConfirmSignUpRoute() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [confirmationCode, setConfirmationCode] = useState("")
  const [cooldown, setCooldown] = useState(0)
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    setEmail(window.sessionStorage.getItem(PENDING_EMAIL_KEY) || "")
  }, [])

  useEffect(() => {
    if (cooldown <= 0) {
      return undefined
    }
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  async function handleConfirm(event) {
    event.preventDefault()
    setError("")
    setIsSubmitting(true)
    try {
      await confirmCognitoAccount({ email, confirmationCode })
      window.sessionStorage.removeItem(PENDING_EMAIL_KEY)
      router.push("/sign-in")
    } catch (err) {
      setError(getCognitoErrorMessage(err, "Could not confirm the account"))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleResend() {
    setError("")
    setIsSubmitting(true)
    try {
      await resendCognitoConfirmationCode(email)
      setCooldown(RESEND_COOLDOWN_SECONDS)
    } catch (err) {
      setError(getCognitoErrorMessage(err, "Could not send a new code"))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className={styles.authPage}>
        <form className={styles.authCard} onSubmit={handleConfirm}>
          <h1>Confirm your email</h1>
          <p>Enter the code sent to your email address.</p>
          <AuthField
            autoComplete="email"
            label="Email address"
            name="email"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="jane@example.com"
            required
            value={email}
          />
          <AuthField
            autoComplete="one-time-code"
            label="Confirmation code"
            name="confirmationCode"
            onChange={(event) => setConfirmationCode(event.target.value)}
            placeholder="Enter the six-digit code"
            required
            value={confirmationCode}
          />
          {error ? <p aria-live="assertive" className={styles.authError} role="alert">{error}</p> : null}
          <button className={styles.authSubmit} disabled={isSubmitting} type="submit">
            {isSubmitting ? "Confirming..." : "Confirm account"}
          </button>
          <span className={styles.authSwap}>
            Didn&apos;t get a code?
            <button disabled={isSubmitting || cooldown > 0} onClick={handleResend} type="button">
              {cooldown > 0 ? `Try again in ${cooldown}s` : "Send a new code"}
            </button>
          </span>
          <span className={styles.authSwap}>Already confirmed?<Link href="/sign-in">Sign in</Link></span>
        </form>
    </section>
  )
}

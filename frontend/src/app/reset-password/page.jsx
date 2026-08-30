"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { AuthField } from "../components/auth/AuthField"
import {
  confirmCognitoPasswordReset,
  getCognitoErrorMessage,
  startCognitoPasswordReset,
} from "../../auth/cognito"
import styles from "../page.module.css"

const RESET_EMAIL_KEY = "stonks_reset_email"
const RESEND_COOLDOWN_SECONDS = 60

export default function ResetPasswordRoute() {
  const router = useRouter()
  const [form, setForm] = useState({
    email: "",
    confirmationCode: "",
    newPassword: "",
  })
  const [cooldown, setCooldown] = useState(0)
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    const email = window.sessionStorage.getItem(RESET_EMAIL_KEY) || ""
    setForm((current) => ({ ...current, email }))
  }, [])

  useEffect(() => {
    if (cooldown <= 0) {
      return undefined
    }
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

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
      await confirmCognitoPasswordReset(form)
      window.sessionStorage.removeItem(RESET_EMAIL_KEY)
      router.push("/sign-in")
    } catch (err) {
      setError(getCognitoErrorMessage(err, "Could not reset the password"))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleResend() {
    setError("")
    setIsSubmitting(true)
    try {
      await startCognitoPasswordReset(form.email)
      setCooldown(RESEND_COOLDOWN_SECONDS)
    } catch (err) {
      if (err?.name === "UserNotFoundException") {
        setCooldown(RESEND_COOLDOWN_SECONDS)
      } else {
        setError(getCognitoErrorMessage(err, "Could not send a new code"))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className={styles.authPage}>
        <form className={styles.authCard} onSubmit={handleSubmit}>
          <h1>Choose a new password</h1>
          <p>Enter the emailed code and a new password.</p>
          <AuthField
            autoComplete="email"
            label="Email address"
            name="email"
            onChange={updateForm}
            placeholder="jane@example.com"
            required
            value={form.email}
          />
          <AuthField
            autoComplete="one-time-code"
            label="Reset code"
            name="confirmationCode"
            onChange={updateForm}
            placeholder="Enter the six-digit code"
            required
            value={form.confirmationCode}
          />
          <AuthField
            autoComplete="new-password"
            label="New password"
            name="newPassword"
            onChange={updateForm}
            placeholder="At least 12 characters"
            password
            required
            value={form.newPassword}
          />
          {error ? <p aria-live="assertive" className={styles.authError} role="alert">{error}</p> : null}
          <button className={styles.authSubmit} disabled={isSubmitting} type="submit">
            {isSubmitting ? "Resetting..." : "Reset password"}
          </button>
          <span className={styles.authSwap}>
            Need a new code?
            <button disabled={isSubmitting || cooldown > 0} onClick={handleResend} type="button">
              {cooldown > 0 ? `Try again in ${cooldown}s` : "Send a new code"}
            </button>
          </span>
          <span className={styles.authSwap}>Back to<Link href="/sign-in">Sign in</Link></span>
        </form>
    </section>
  )
}

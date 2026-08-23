"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { AuthField } from "../components/auth/AuthField"
import { AppFrame } from "../components/layout/AppFrame"
import {
  getCognitoErrorMessage,
  startCognitoPasswordReset,
} from "../../auth/cognito"
import styles from "../page.module.css"

const PENDING_EMAIL_KEY = "stonks_pending_email"
const RESET_EMAIL_KEY = "stonks_reset_email"

export default function ForgotPasswordRoute() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    setEmail(window.sessionStorage.getItem(PENDING_EMAIL_KEY) || "")
  }, [])

  async function handleSubmit(event) {
    event.preventDefault()
    setError("")
    setIsSubmitting(true)
    const normalizedEmail = email.trim().toLowerCase()
    try {
      await startCognitoPasswordReset(normalizedEmail)
      window.sessionStorage.setItem(RESET_EMAIL_KEY, normalizedEmail)
      window.sessionStorage.removeItem(PENDING_EMAIL_KEY)
      router.push("/reset-password")
    } catch (err) {
      if (err?.name === "UserNotFoundException") {
        window.sessionStorage.setItem(RESET_EMAIL_KEY, normalizedEmail)
        router.push("/reset-password")
        return
      }
      setError(getCognitoErrorMessage(err, "Could not start the password reset"))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AppFrame>
      <section className={styles.authPage}>
        <form className={styles.authCard} onSubmit={handleSubmit}>
          <h1>Reset your password</h1>
          <p>If an account exists for this email, we will send a reset code.</p>
          <AuthField
            autoComplete="email"
            label="Email address"
            name="email"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="jane@example.com"
            required
            value={email}
          />
          {error ? <p className={styles.authError}>{error}</p> : null}
          <button className={styles.authSubmit} disabled={isSubmitting} type="submit">
            {isSubmitting ? "Sending..." : "Send reset code"}
          </button>
          <span className={styles.authSwap}>Remembered your password?<Link href="/sign-in">Sign in</Link></span>
        </form>
      </section>
    </AppFrame>
  )
}

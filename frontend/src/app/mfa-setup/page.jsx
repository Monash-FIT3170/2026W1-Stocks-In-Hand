"use client"

import Link from "next/link"
import { useState } from "react"
import { AuthField } from "../components/auth/AuthField"
import {
  completeCognitoTotpSetup,
  getCognitoErrorMessage,
  isCognitoAuthEnabled,
  startCognitoTotpSetup,
} from "../../auth/cognito"
import styles from "../page.module.css"

export default function MfaSetupRoute() {
  const [setup, setSetup] = useState(null)
  const [code, setCode] = useState("")
  const [error, setError] = useState("")
  const [complete, setComplete] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function beginSetup() {
    setError("")
    setIsSubmitting(true)
    try {
      setSetup(await startCognitoTotpSetup())
    } catch (err) {
      setError(getCognitoErrorMessage(err, "Could not start authenticator setup"))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function confirmSetup(event) {
    event.preventDefault()
    setError("")
    setIsSubmitting(true)
    try {
      await completeCognitoTotpSetup(code)
      setComplete(true)
    } catch (err) {
      setError(getCognitoErrorMessage(err, "Could not verify the authenticator code"))
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!isCognitoAuthEnabled()) {
    return (
      <section className={styles.authPage}>
          <div className={styles.authCard}>
            <h1>Authenticator setup</h1>
            <p>This option becomes available after Cognito authentication is enabled.</p>
            <Link href="/">Return home</Link>
          </div>
      </section>
    )
  }

  return (
    <section className={styles.authPage}>
        <form className={styles.authCard} onSubmit={confirmSetup}>
          <h1>Set up an authenticator</h1>
          {complete ? (
            <>
              <p>Your authenticator is enabled. Administrators must keep it enabled.</p>
              <Link href="/watchlist">Return to your watchlist</Link>
            </>
          ) : setup ? (
            <>
              <p>Add this key to Microsoft Authenticator, Google Authenticator, or another TOTP app.</p>
              <div className={styles.securityNote}><code>{setup.sharedSecret}</code></div>
              <a href={setup.setupUri}>Open authenticator app</a>
              <AuthField
                autoComplete="one-time-code"
                label="Authenticator code"
                name="code"
                onChange={(event) => setCode(event.target.value)}
                placeholder="Enter the six-digit code"
                required
                value={code}
              />
              <button className={styles.authSubmit} disabled={isSubmitting} type="submit">
                {isSubmitting ? "Checking..." : "Enable authenticator"}
              </button>
            </>
          ) : (
            <>
              <p>Use a time-based one-time password for stronger account security.</p>
              <button className={styles.authSubmit} disabled={isSubmitting} onClick={beginSetup} type="button">
                {isSubmitting ? "Starting..." : "Start setup"}
              </button>
            </>
          )}
          {error ? <p aria-live="assertive" className={styles.authError} role="alert">{error}</p> : null}
        </form>
    </section>
  )
}

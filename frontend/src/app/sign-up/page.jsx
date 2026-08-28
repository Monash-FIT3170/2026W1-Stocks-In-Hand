"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { AuthField } from "../components/auth/AuthField"
import { apiFetch } from "../lib/api"
import { friendlyAuthError } from "../lib/authErrors"
import styles from "../page.module.css"

const AUTH_STORAGE_KEY = "stonks_signed_in"

function getErrorMessage(data, fallback) {
  if (Array.isArray(data.detail)) {
    return data.detail.map((error) => error.msg).join(", ")
  }

  if (typeof data.detail === "string") {
    return data.detail
  }

  return fallback
}

export default function SignUpRoute() {
  const router = useRouter()
  const [form, setForm] = useState({ name: "", email: "", password: "" })
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
      const response = await apiFetch("/auth/sign-up", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      })
      const data = await response.json().catch(() => ({}))

      if (!response.ok) {
        throw new Error(friendlyAuthError(getErrorMessage(data, "Could not create account"), "Could not create account"))
      }

      window.localStorage.setItem(AUTH_STORAGE_KEY, "true")
      window.dispatchEvent(new Event("stonks-auth-changed"))
      router.push("/watchlist")
    } catch (err) {
      setError(
        err instanceof TypeError
          ? "Could not reach the account service. Check your connection and try again."
          : friendlyAuthError(err.message, "Could not create account")
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className={styles.authPage}>
        <form className={styles.authCard} onSubmit={handleSubmit}>
          <h1>Create your watchlist</h1>
          <p>Create a watchlist for the ASX companies you want to monitor.</p>
          <AuthField
            autoComplete="name"
            label="Full name"
            maxLength={100}
            name="name"
            onChange={updateForm}
            placeholder="E.g. Jane Doe"
            required
            value={form.name}
          />
          <AuthField
            autoComplete="email"
            label="Email address"
            maxLength={320}
            name="email"
            onChange={updateForm}
            placeholder="jane@example.com"
            required
            value={form.email}
          />
          <AuthField
            autoComplete="new-password"
            label="Password"
            minLength={8}
            name="password"
            onChange={updateForm}
            placeholder="At least 8 characters"
            password
            required
            value={form.password}
          />
          {error ? <p aria-live="assertive" className={styles.authError} role="alert">{error}</p> : null}
          <button className={styles.authSubmit} disabled={isSubmitting} type="submit">
            {isSubmitting ? "Creating…" : "Create account"}
          </button>
          <span className={styles.authSwap}>Already have an account?<Link href="/sign-in">Sign in</Link></span>
        </form>
        <div className={styles.securityNote}>Choose a unique password. It is never displayed in the app.</div>
    </section>
  )
}

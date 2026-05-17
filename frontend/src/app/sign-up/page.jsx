"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { AuthField } from "../components/auth/AuthField"
import { AppFrame } from "../components/layout/AppFrame"
import styles from "../page.module.css"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
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
      const response = await fetch(`${API_URL}/auth/sign-up`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      })
      const data = await response.json().catch(() => ({}))

      if (!response.ok) {
        throw new Error(getErrorMessage(data, "Could not create account"))
      }

      window.localStorage.setItem(AUTH_STORAGE_KEY, "true")
      router.push("/watchlist")
    } catch (err) {
      setError(
        err instanceof TypeError
          ? "Could not reach the backend. Make sure the API is running on port 8000."
          : err.message
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AppFrame>
      <section className={styles.authPage}>
        <form className={styles.authCard} onSubmit={handleSubmit}>
          <h1>Start your investing journey</h1>
          <p>Join thousands of retail investors getting clear, plain-English ASX insights.</p>
          <AuthField
            autoComplete="name"
            label="Full name"
            name="name"
            onChange={updateForm}
            placeholder="E.g. Jane Doe"
            required
            value={form.name}
          />
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
            autoComplete="new-password"
            label="Password"
            name="password"
            onChange={updateForm}
            placeholder="At least 8 characters"
            password
            required
            value={form.password}
          />
          {error ? <p className={styles.authError}>{error}</p> : null}
          <button className={styles.authSubmit} disabled={isSubmitting} type="submit">
            {isSubmitting ? "Creating..." : "Create account"}
          </button>
          <span className={styles.authSwap}>Already have an account?<Link href="/sign-in">Sign in</Link></span>
        </form>
        <div className={styles.securityNote}>Institutional-grade security for your ASX data</div>
      </section>
    </AppFrame>
  )
}

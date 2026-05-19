"use client"

import { useRouter } from "next/navigation"
import { useEffect } from "react"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
const AUTH_STORAGE_KEY = "stonks_signed_in"

export default function SignOutRoute() {
  const router = useRouter()

  useEffect(() => {
    async function signOut() {
      try {
        await fetch(`${API_URL}/auth/sign-out`, {
          method: "POST",
          credentials: "include",
        })
      } finally {
        window.localStorage.removeItem(AUTH_STORAGE_KEY)
        router.replace("/")
      }
    }

    signOut()
  }, [router])

  return null
}

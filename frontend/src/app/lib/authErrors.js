export function friendlyAuthError(message, fallback) {
  const value = String(message || "").trim()
  const lower = value.toLowerCase()

  if (lower.includes("invalid email or password")) {
    return "The email or password is not correct."
  }
  if (lower.includes("valid email") || lower.includes("email address")) {
    return "Enter a valid email address."
  }
  if (lower.includes("at least 8") || (lower.includes("password") && lower.includes("8"))) {
    return "Use a password with at least 8 characters."
  }
  if (lower.includes("field required") || lower.includes("is required")) {
    return "Complete all required fields and try again."
  }
  return value || fallback
}

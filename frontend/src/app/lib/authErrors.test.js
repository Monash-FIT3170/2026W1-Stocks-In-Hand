import { expect, test } from "vitest"

import { friendlyAuthError } from "./authErrors"


test("invalid credentials are not reported as an email-format error", () => {
  expect(friendlyAuthError("Invalid email or password", "Could not sign in")).toBe(
    "The email or password is not correct.",
  )
})


test("actual email validation errors remain friendly", () => {
  expect(
    friendlyAuthError("value is not a valid email address", "Could not sign in"),
  ).toBe("Enter a valid email address.")
})

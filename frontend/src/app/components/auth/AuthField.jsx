import styles from "../../page.module.css"
import { EyeIcon } from "../icons"

// Shared auth input used by the sign-in and sign-up forms.
export function AuthField({
  label,
  name,
  placeholder,
  password = false,
  value,
  onChange,
  required = false,
  autoComplete,
}) {
  return (
    <label className={styles.field}>
      <span>{label}</span>
      <div>
        <input
          autoComplete={autoComplete}
          name={name}
          onChange={onChange}
          placeholder={placeholder}
          required={required}
          type={password ? "password" : "text"}
          value={value}
        />
        {password && <EyeIcon />}
      </div>
    </label>
  )
}

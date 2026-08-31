import styles from "../research/ResearchSurface.module.css"
import { EmergingThemes } from "./EmergingThemes"
import { KeyNumbers } from "./KeyNumbers"

export function BriefAside({ data = {} }) {
  return (
    <aside className={styles.briefAside}>
      <KeyNumbers items={data.key_numbers || []} />
      <EmergingThemes themes={data.themes || []} />
    </aside>
  )
}

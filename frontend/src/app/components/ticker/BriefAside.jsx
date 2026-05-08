import styles from "../../page.module.css"
import { EmergingThemes } from "./EmergingThemes"
import { KeyNumbers } from "./KeyNumbers"
import { MarketIntelligence } from "./MarketIntelligence"

export function BriefAside() {
  return <aside className={styles.briefAside}><KeyNumbers /><MarketIntelligence /><EmergingThemes /></aside>
}

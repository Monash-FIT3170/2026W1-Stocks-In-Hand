import styles from "../../page.module.css"
import { EmergingThemes } from "./EmergingThemes"
import { KeyNumbers } from "./KeyNumbers"
import { MarketIntelligence } from "./MarketIntelligence"

// Shared right-hand sidebar across all ticker brief tabs.
// Summary, News, and Deep Dive should all keep using this component so key numbers,
// market intelligence, and themes stay visually consistent across the brief experience.
export function BriefAside({ data = {} }) {
  return (
    <aside className={styles.briefAside}>
      <KeyNumbers items={data.key_numbers || []} />
      <MarketIntelligence intelligence={data.market_intelligence || {}} />
      <EmergingThemes themes={data.themes || []} />
    </aside>
  )
}

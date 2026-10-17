# StonksInHand UI audit

Date: 2026-08-31  
Branch: `3.2.3.86d7m4q2x-integration-ui-improvements`  
Scope: Next.js frontend in `frontend/src/app`

## Audit health score

| Dimension | Score | Key finding |
| --- | ---: | --- |
| Accessibility | 3/4 | Strong semantics and focus styling; dialog focus containment and compact text remain concerns. |
| Performance | 3/4 | No image or animation burden; route-wide client shell and monolithic CSS increase avoidable work. |
| Responsive design | 2/4 | Breakpoints exist, but mobile navigation and horizontally scrolling tabs are unresolved. |
| Theming | 1/4 | Tokens exist, but hard-coded colors dominate and there is no dark-mode strategy. |
| Implementation integrity | 2/4 | The interface is coherent enough to use, but the design system is fragmented and still reads as a prototype. |
| **Total** | **11/20** | **Acceptable — significant UI work is justified.** |

## Implementation integrity verdict

**Fail for production polish; pass for prototype usability.** The product has a recognizable green, mint, and neutral visual language, shared shell, semantic page structure, and reusable ticker components. However, the implementation does not yet express that language through a durable system. `page.module.css` is over 2,000 lines and styles unrelated routes, while newer screens use isolated modules with separate values. The mechanical Impeccable detector also flagged the orange side-border treatment at `frontend/src/app/page.module.css:839` as a generic card accent pattern.

## Executive summary

- No P0 blockers found.
- 3 P1 major issues, 5 P2 issues, and 2 P3 polish issues.
- Preserve the existing accessibility foundations and product-specific source-aware copy.
- Prioritize a small design system and app-shell/mobile navigation redesign before polishing individual cards.
- Treat this as an **Operate** interface: fast scanning, clear provenance, and calm confidence should outrank decorative effects.

## Findings

### P1 — Mobile navigation does not scale

- **Location:** `frontend/src/app/components/layout/AppFrame.module.css:237-263`; `frontend/src/app/components/layout/AppFrame.jsx:99-108`
- **Category:** Responsive design / navigation
- **Impact:** Authenticated users can receive six primary actions in a horizontally scrolling sticky header. Discoverability is poor, the current location can be off-screen, and the two-row header consumes substantial vertical space.
- **Recommendation:** Introduce a deliberate mobile navigation pattern with a compact top bar and menu/drawer. Keep the top-level set to the highest-frequency destinations and move account/security/settings into an account menu.
- **Suggested command:** `$impeccable adapt`

### P1 — Styling architecture prevents consistent polish

- **Location:** `frontend/src/app/page.module.css:1-2104`; `frontend/src/app/settings/notifications/page.module.css`; `frontend/src/app/unsubscribe/page.module.css`
- **Category:** Theming / implementation integrity
- **Impact:** Shared route primitives, ticker views, auth screens, dialogs, and cards are coupled in one very large CSS module while newer pages establish parallel systems. Small visual changes can create regressions and inconsistent variants.
- **Recommendation:** Establish global semantic tokens, extract reusable primitives (button, field, card, badge, section header, empty state), and colocate page-specific layout rules. Document the source of truth in `DESIGN.md`.
- **Suggested command:** `$impeccable document`

### P1 — Color tokens are incomplete and inconsistently applied

- **Location:** `frontend/src/app/components/layout/AppFrame.module.css:7-22`; hard-coded values throughout `frontend/src/app/page.module.css`, `settings/notifications/page.module.css`, and `unsubscribe/page.module.css`
- **Category:** Theming / accessibility
- **Impact:** Similar surfaces, borders, muted text, positive states, and warning states use unrelated literals. This makes contrast auditing, dark mode, and coherent iteration difficult.
- **Recommendation:** Replace literals with semantic roles such as `--color-bg`, `--color-surface`, `--color-text-secondary`, `--color-border`, `--color-positive`, `--color-warning`, and interactive state tokens. Verify every text pair to WCAG AA.
- **Suggested command:** `$impeccable colorize`

### P2 — Dialog semantics are present but focus management is incomplete

- **Location:** `frontend/src/app/watchlist/page.jsx:428-466`
- **Category:** Accessibility
- **Impact:** The add-company modal has `role="dialog"`, labels, and Escape handling, but there is no verified focus trap, initial focus transfer, scroll lock, or focus restoration. Keyboard users can move into content behind the modal.
- **WCAG:** 2.4.3 Focus Order; 2.4.11 Focus Not Obscured
- **Recommendation:** Move focus to the search input when opened, contain Tab/Shift+Tab, lock background scroll, make background content inert, and restore focus to the trigger when closed.
- **Suggested command:** `$impeccable harden`

### P2 — Dense financial metadata is too small

- **Location:** repeated `11px`, `12px`, and `13px` declarations in `frontend/src/app/page.module.css`, including lines 386, 469, 597, 798, 983, 1068, 1137, and 1287
- **Category:** Accessibility / typography
- **Impact:** Uppercase, tracked labels and source metadata become hard to scan on mobile and under text zoom, especially for older investors or low-vision users.
- **Recommendation:** Use a 14px practical floor for meaningful metadata, reserve 12px for truly tertiary content, reduce letter spacing, and test at 200% zoom.
- **Suggested command:** `$impeccable typeset`

### P2 — Search lacks an explicit action and richer feedback

- **Location:** `frontend/src/app/page.jsx:81-84`; `frontend/src/app/search/page.jsx:115-118`
- **Category:** Forms / interaction
- **Impact:** Search is submitted only by pressing Enter. The icon looks decorative, there is no visible Search button or clear action, and loading/suggestion behavior is minimal.
- **Recommendation:** Add a visible submit action, clear button when populated, helpful keyboard behavior, and an intentional suggestions/recent-search state where appropriate.
- **Suggested command:** `$impeccable clarify`

### P2 — Horizontal tabs are a workaround, not a responsive model

- **Location:** `frontend/src/app/page.module.css:2086-2089`
- **Category:** Responsive design
- **Impact:** Three fixed 150px tab columns force horizontal scrolling on narrow screens without an obvious affordance that more content exists.
- **Recommendation:** Use fit-content tabs with edge fade/scroll indicators or replace them with a compact segmented/select pattern on small screens. Ensure the active tab scrolls into view.
- **Suggested command:** `$impeccable adapt`

### P2 — Inline body styling bypasses the token system

- **Location:** `frontend/src/app/layout.jsx:11`
- **Category:** Theming / implementation integrity
- **Impact:** Background, text color, margin, and font are defined outside the design system, making global typography and theme changes less reliable.
- **Recommendation:** Move root styling into a global stylesheet and define typography, background, text, color-scheme, and rendering defaults centrally.
- **Suggested command:** `$impeccable document`

### P3 — Visual hierarchy relies heavily on white cards and pills

- **Location:** `frontend/src/app/page.module.css:190-250` and repeated card/pill selectors
- **Category:** Visual polish
- **Impact:** Many screens have similar card weight, radius, shadow, and pill treatment, so important market information competes with secondary metadata.
- **Recommendation:** Reduce container count, use spacing and typography for grouping, reserve elevated surfaces for actionable or high-priority content, and create a more distinctive provenance treatment.
- **Suggested command:** `$impeccable layout`

### P3 — Generic side-border warning treatment

- **Location:** `frontend/src/app/page.module.css:839`
- **Category:** Implementation integrity / visual polish
- **Impact:** The thick orange side rule looks like a generic alert-card shortcut and does not reinforce the product identity.
- **Recommendation:** Replace it with a semantic icon, restrained tint, label, and border treatment consistent with the final status system.
- **Suggested command:** `$impeccable polish`

## Positive findings to preserve

- A skip link, visible `:focus-visible` treatment, semantic `main`, nav landmarks, and route announcement are implemented in `AppFrame`.
- Most interactive controls meet the 44px target size.
- Forms use visible labels and nearby live-region error messages.
- The watchlist modal has a semantic dialog role and accessible name/description.
- Content avoids unsupported investment claims and repeatedly keeps source provenance close to summaries.
- Layouts already have tablet and mobile breakpoints; the work is refinement rather than a desktop-only rescue.
- The UI uses SVG icon components rather than emoji or icon-font placeholders.

## Recommended action sequence

1. **P1 — `$impeccable document`:** define the current product character, tokens, type scale, spacing, elevation, and reusable components in `DESIGN.md`.
2. **P1 — `$impeccable adapt`:** redesign the authenticated mobile app shell and tab behavior.
3. **P1 — `$impeccable colorize`:** consolidate semantic color roles and verify contrast.
4. **P2 — `$impeccable typeset`:** improve density and hierarchy across ticker, announcement, and watchlist screens.
5. **P2 — `$impeccable harden`:** complete modal focus management and interaction edge cases.
6. **P2 — `$impeccable layout`:** reduce card/pill repetition and establish clearer information priority.
7. **P3 — `$impeccable polish`:** run the final responsive and interaction pass after implementation.

## Verification notes

- The Impeccable detector was run against `frontend/src/app`; it returned one verified warning at `page.module.css:839`.
- A live browser pass was not completed during this audit because the available package manager attempted to migrate the existing `node_modules` installation and the test runner could not start non-interactively. Source-level findings are therefore distinguished from rendered claims; desktop/mobile screenshots, keyboard traversal, axe, console, network, and Core Web Vitals remain part of the implementation verification pass.

You can ask for these improvements one at a time, all at once, or in any preferred order. Re-run `$impeccable audit` after fixes to measure the score again.

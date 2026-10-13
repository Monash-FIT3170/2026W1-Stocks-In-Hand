# Quartr redesign finish review

Independent review, 13 October 2026. Code-led direction; no approved visual comp. Reviewed the implementation and stored render evidence without opening a browser or editing application code.

## 1. Disposition

**Fix, then ship the reviewed scope.** The redesign is substantially faithful to the pinned Quartr direction and the captured public/research screens are no longer significantly worse in hierarchy, composition, type or surface craft. A rebuild is unwarranted. Three narrow mobile-control/accessibility issues remain below. None requires decorative pictures, invented financial content or authentication changes. No existing evidence needs recapture because it is invalid; capture the corrected open-control states as verification of those fixes.

## 2. Contract fidelity

The first body child in `frontend/src/app/layout.jsx` preserves the direction contract: wide source-first compositions, distinct reading/evidence/controls, official self-hosted Inter Variable, near-black text, stone evidence surfaces, cobalt interactions and a 1360px frame. Source and browser metadata support the specified heading weight of 550. The font licence is present beside the WOFF2.

Against Quartr's public API, overview, hedge-feature and pricing references, the implementation carries the useful qualities rather than copying its pictures: controlled display scale, aligned broad columns, understated rectangular controls, close heading/body groups and substantial neutral supporting regions. Home's actual filing exhibit gives the hero useful visual mass. Feed controls, white record document and stone activity rail have distinct purposes. The company views share a balanced identity and understated underline navigation; analysis, selected evidence and chronological/index reading differ appropriately. Search has a readable ledger rather than empty financial-stat panels. About, source directory, terms and forms have appropriately different compositions within one family.

The user-width 1294px feed and summary captures preserve those relationships. The supplemental 1074px summary remains readable with a 300px evidence column. Mobile layouts stack coherently and avoid title clipping. Pending filing analysis is represented compactly while existing substantive topical research remains primary. Empty classification is honest. The absence of decorative photography follows the user constraint and is not a fidelity failure.

## 3. Material findings and remedies

### F1 — Mobile date popover is constrained to half the filter strip

**Priority: P2.** `frontend/src/app/components/research/ResearchSurface.module.css`: mobile `.dateRangePopover` sets `width: 100%`, while `.dateRangePicker` is the positioned containing block and occupies one of two columns. In the 390px layout this yields approximately 150px overall width and roughly 110px after its padding. `.rangePresets` keeps both padded links in one unwrapped flex row; the controls cannot fit cleanly, and native date inputs get a similarly narrow region. The existing closed-filter capture does not show this open state, so its empty overflow list cannot dismiss this source-level problem.

**Remedy:** give the opened mobile date controls the width of the full filter strip, either by anchoring the popover to that strip or expanding the open picker across its grid. Keep all presets, both date inputs and their explanatory text within the viewport. Verify the open state at 390px and 320px, including a selected range.

### F2 — Source-record search loses its reliable label on mobile

**Priority: P2.** `frontend/src/app/components/company/SourceLibrary.jsx`, the search input in `.libraryTools`; `frontend/src/app/components/company/CompanyWorkspace.module.css`, mobile `.libraryTools .searchControl > span { display: none; }`. The visible label is removed from the accessibility tree and the input has no explicit accessible name. The truncated placeholder is an inadequate replacement for a persistent search label.

**Remedy:** keep the label visually hidden rather than `display: none`, or add an explicit `aria-label="Search records"` while retaining the desktop label. Verify the accessible name at the mobile breakpoint. The change-record index and return-to-reader mechanism itself is clearly implemented and represented by `sources-mobile-index.png`.

### F3 — Full-screen mobile navigation leaves covered content reachable

**Priority: P2.** `frontend/src/app/components/layout/AppFrame.jsx`, the `mobileOpen` body-scroll effect and the main/footer render. The mobile panel covers the remaining viewport and locks scrolling, but main/footer remain focusable and exposed to assistive technology. Tabbing after the panel can move focus to content hidden behind it. Escape closes the panel without restoring mobile focus to the toggle.

**Remedy:** make covered main/footer inert during the open mobile navigation state, preserve a usable close/menu toggle, and restore focus to it on keyboard close. Ensure the mechanism resets correctly on navigation and breakpoint changes. Verify keyboard traversal of the open panel at 390px. This is shell interaction work and does not alter the account flow.

## 4. Craft and accessibility

The rendered spacing and type hierarchy are convincing: 44px browsing titles, 32px research titles, 28px section headings, 18–20px item headings and 16px research copy form a disciplined scale. Long source titles wrap instead of being ellipsized into unreadable labels. The text measure is bounded in CSS; metadata is attached to its record and stays quieter than content. The long history capture maintains orderly chronological chapters through its final entry, with compact pending entries and clear original citations. The summary's lower context ledger and honest classification/discussion states remain consistent with its opening.

The shared system explicitly themes focus, caret, selection, scrollbars, underline offsets and tabular numerals. Neutral text colours are suitably dark for the white, cool and stone surfaces in the reviewed states. Controls use meaningful 44–48px targets, SVG strokes are consistent, headings retain a useful semantic outline, forms have actual labels and native input types, errors and loading states have live/alert roles, and reduced motion is handled globally. Content is visible by default. The small home-exhibit entrance is restrained; no ornamental animation is needed to make this research product premium.

The remaining accessibility findings are F2 and F3. Source-level evidence supports hover, loading, disabled, error and empty styles; their presence is not proof that every possible runtime branch has been exercised. The mechanical detector's empty result is supporting evidence, not a substitute for this review.

## 5. Scope and limitations

Inspected all required desktop/mobile captures: home, announcements, summary, source records, history, search, signup, about, data sources, terms and unsubscribe. Also inspected the final feed/summary 1294px captures, the 1074px summary, the mobile source index and legible regional crops of the full summary/history captures. Compared with the stored public Quartr reference images and documented measurements. Read the shared shell/tokens, page CSS, research/company CSS and components, source controls, auth field system and relevant account/settings/result presentation code.

Captured research/feed content uses actual returned COH data. Latest filing analysis is legitimately pending; topical analysis is substantive. Review crops made only for inspection are named `*-review-*.png` and are not shipping assets.

Authenticated watchlist and alert-settings renders remain visually unverified. Other auth/result runtime branches are not covered state by state, and no auth submission, account mutation or token consumption was performed. Builder reports a passing production export of 60 pages and 30 frontend tests; this reviewer did not independently rerun them. This verdict applies to the inspected scope and does not certify all states of the entire application or Quartr's authenticated product. Premium equivalence here is an informed qualitative judgment about the stated design dimensions, not a universal numerical claim.

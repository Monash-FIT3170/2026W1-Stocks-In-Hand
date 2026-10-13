---
name: StonksInHand
description: A calm source-first ASX research workspace with distinct reading, evidence and control regions.
colors:
  canvas: "#fbfcfc"
  canvas-subtle: "#f4f6f8"
  surface: "#fff"
  surface-context: "#f3f2ef"
  ink: "#101214"
  ink-secondary: "#4e5965"
  ink-tertiary: "#626a73"
  line: "#dfe4e8"
  line-strong: "#818991"
  brand: "#2f5bea"
  brand-soft: "#e9eeff"
  positive: "#13795b"
  positive-soft: "#e5f5ef"
  warning: "#8a5b00"
  warning-soft: "#fff3d6"
  negative: "#b4233b"
  negative-soft: "#fdecef"
  focus: "#2f5bea"
  overlay: "rgb(16 18 20 / 48%)"
  action-hover: "#292c30"
  context-line: "#d4d5d2"
typography:
  display:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "clamp(48px, 4.8vw, 64px)"
    fontWeight: 550
    lineHeight: 1.08
    letterSpacing: "-0.04em"
  public-headline:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "52px"
    fontWeight: 550
    lineHeight: 1.1
    letterSpacing: "-0.04em"
  browse-headline:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "44px"
    fontWeight: 550
    lineHeight: 1.1
    letterSpacing: "-0.035em"
  company-identity:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "40px"
    fontWeight: 550
    lineHeight: 1.15
    letterSpacing: "-0.035em"
  task-headline:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "34px"
    fontWeight: 550
    lineHeight: 1.15
    letterSpacing: "-0.03em"
  research-headline:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "32px"
    fontWeight: 550
    lineHeight: 1.2
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "28px"
    fontWeight: 550
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "20px"
    fontWeight: 550
    lineHeight: 1.3
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.65
  intro:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 500
  primary-action:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 550
  metadata:
    fontFamily: "Inter Variable, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  tag: "4px"
  control: "6px"
  panel: "8px"
spacing:
  label: "8px"
  compact: "12px"
  related: "16px"
  group: "20px"
  panel: "24px"
  section: "28px"
  region: "32px"
  chapter: "40px"
  composition: "48px"
  public: "64px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    typography: "{typography.primary-action}"
    rounded: "{rounded.control}"
    padding: "0 18px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
    textColor: "{colors.surface}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 16px"
  button-secondary-hover:
    backgroundColor: "{colors.canvas-subtle}"
  input-search:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 12px"
  company-navigation:
    textColor: "{colors.ink-secondary}"
    padding: "12px 0"
  ticker-tag:
    backgroundColor: "{colors.surface-context}"
    textColor: "{colors.ink}"
    rounded: "{rounded.tag}"
    padding: "0 8px"
  sentiment-neutral:
    backgroundColor: "{colors.canvas-subtle}"
    textColor: "{colors.ink-secondary}"
    rounded: "{rounded.tag}"
    padding: "4px 7px"
  reading-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "32px"
  evidence-panel:
    backgroundColor: "{colors.surface-context}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "28px"
  source-link:
    textColor: "{colors.ink}"
  topic-disclosure:
    textColor: "{colors.ink}"
    padding: "16px 0"
---

# Design System: StonksInHand

## Overview

**Creative North Star: "Source-first research workspace"**

Wide compositions give reading, evidence and controls their own recognisable regions. Self-hosted Inter Variable, near-black ink and quiet neutral surfaces keep the product calm, exact and task-oriented. Headings carry confident medium emphasis; original material remains visually close to the research it supports.

The user-selected Quartr public reference informs restraint, horizontal balance, grouping and navigation. StonksInHand retains its own identity and source-led workflows. Real source exhibits, document readers and ledgers supply visual substance; decorative photography and copied Quartr assets do not belong to this implementation. Content is visible by default, with short motion limited to interaction feedback and the home exhibit.

**Key Characteristics:**

- Wide frame with bounded reading measures.
- White documents, stone evidence and cool control regions.
- Inter Variable headings at 550; body copy at 400.
- Black principal actions and cobalt interaction feedback.
- Quiet dividers, small rectangular corners and explicit source states.

This records the implementation completed on 13 October 2026. The direction contract in [layout.jsx](frontend/src/app/layout.jsx) and source tokens govern the built world; earlier plans are proposals. Reference and QA captures are evidence only: no shipping raster imagery was introduced. The final verdict is **Ship the reviewed scope**. Authenticated watchlist/settings and unexercised authentication/result branches remain outside visual verification; their styles are documented from source.

## Colors

Near-black reading ink sits on white, cool and stone neutrals; cobalt and labelled semantic colours explain interaction and state. Frontmatter values match [tokens.css](frontend/src/app/tokens.css). The action-hover and context-line values recur as literals in component styles.

### Primary

- **Cobalt interaction (brand/focus):** keyboard outlines, caret, selection, selected records, active settings controls and source-link hover. Pale brand-soft surfaces mark selection or preview context.
- **Near-black action ink (ink):** principal submission, original-source and account actions share primary text ink. action-hover supplies their charcoal hover state.

### Neutral

- **Quiet canvas:** page and navigation background.
- **Cool controls:** tool strips, neutral states, hover backgrounds and secondary disclosures.
- **White document:** readers, summaries, history, forms and result panels.
- **Stone context:** evidence, source index, contents, trending and public exhibits.
- **Secondary/tertiary ink:** explanations and quieter metadata respectively.
- **Fine/strong line:** region boundaries versus field and secondary-action borders. context-line separates items inside stone regions.
- **Overlay:** watchlist modal backdrop, without glass surface effects.

Positive, warning and negative colours and their soft backgrounds belong to labelled classifications, verification states and feedback. They are state roles, not additional brand accents. Compatibility aliases do not establish a second palette.

**The Interaction Colour Rule.** Cobalt identifies focus, selection, caret and interactive emphasis. Principal filled actions use near-black ink; financial classifications use their labelled semantic colours.

## Typography

**Display and body font:** official self-hosted Inter Variable, with Arial and sans-serif fallback. The WOFF2 and OFL licence live in [fonts](frontend/src/app/fonts/); Next's local font supplies `--font-inter`. There is no separate display or general-purpose monospace family.

Heading emphasis uses weight 550; ordinary paragraphs use 400. Quotes, ranks and ledgers use tabular numerals where implemented. Frontmatter records actual desktop roles, rather than a proposed mathematical scale.

### Hierarchy

- **Display:** home introduction's fluid role becomes 52px at the intermediate breakpoint and 38px on mobile.
- **Public headline:** About/Data sources titles; 34px mobile.
- **Browse headline:** feed/search/watchlist titles; 32px mobile.
- **Company identity:** separate from the view title; 34px at 1199px and 28px mobile. Split account introductions use this desktop scale.
- **Task headline:** contained account/settings/result titles; 28px mobile.
- **Research headline:** current company view; 26px mobile.
- **Headline:** sections and chapters. Reader/history titles use 28px/1.3, then 22px mobile; summary/feed section headings become 24px.
- **Title:** evidence/context headings. Topic titles use 18px; feed records use 22px/1.35, then 20px/1.4 below 640px.
- **Body:** substantial research and source prose uses 16px/1.65, usually bounded at 72ch. Introductory copy uses the 18px role, typically 16–17px mobile.
- **Label/metadata:** controls use 14px, attribution usually 13px, and fine print 12px. Ordinary readable labels replace decorative uppercase eyebrows.

**The Reading Hierarchy Rule.** Keep the company identity, view title, chapter heading, record title and metadata visually distinct. Let long titles wrap and keep substantial research copy at a bounded reading measure.

## Layout

The shared outer frame is 1360px. Main desktop gutters are 32px, becoming 24px at 1199px and 16px at 767px; shell gutters tighten separately at 1000px. Application pages generally use 48px top/80px bottom padding, then 32px/56px mobile. Company identity provides its own top region.

Wide relationships depend on actual content: home pairs introduction/exhibit (1.15fr/.85fr, 64px gap); feed pairs reading/context (1.85fr/.85fr, 32px gap); summary pairs reading/evidence (1.85fr with a 300px-minimum .85fr rail); source records pair a 280px-minimum index and larger reader; history uses a 250px contents rail. Reading stays bounded within these compositions. Terms uses a 1104px frame and 200px contents column; sign-in/signup uses a 1040px composition and 480px form column; unsubscribe uses a 540px result panel.

Spacing expresses relationships: 8px label gaps, 12–16px attached content gaps, 20–32px panel/group spacing and 40–64px independent regions. Home opens with 88px/96px desktop vertical padding and 40px/56px mobile. Apply the relationship rather than every step everywhere.

Responsive changes are specific to the component:

- At 1199px, gutters/padding tighten and watchlist becomes two columns.
- At 1050px, feed introductory scope disappears and its context rail becomes 290px.
- At 1000px, summary evidence moves into the open topic, remaining context uses two columns and history's rail narrows to 210px.
- At 850px, alert status moves before its form.
- At 767px, home, feed, search rows, watchlist, account splits, documents and history stack. Sources show the selected reader first; Change record exposes the index, and returning moves focus/scroll to the reader. Feed controls retain two columns, but the open date popover spans the full filter strip and date fields stack. Source search has an explicit accessible name when its visible label is hidden.
- Mobile shell navigation fills the viewport below its 64px header. Main/footer/skip link are inert while open; Escape focuses the toggle, and crossing 768px clears the mobile state.
- Below 640px, feed records tighten spacing and title scale.

Desktop sticky context/contents begins at 104px. Native disclosures keep mobile contents compact. Text and URLs wrap instead of forcing horizontal overflow.

## Elevation & Depth

Surface tone, spacing and fine rules carry most depth. Resting white documents and stone context remain flat. Floating date/filter controls use the soft shadow (`0 16px 40px rgb(16 18 20 / 10%)`); the modal uses an overlay backdrop. Mobile contained date/filter controls remove the shadow.

**The Flat Region Rule.** Reading and evidence panels rest flat. Surface tone, spacing and dividers explain their relationship; the soft shadow is reserved for floating controls.

Motion stays functional: button backgrounds use 160ms, navigation/menu changes 180ms, and the home exhibit translates 8px over 340ms. There is no global reveal observer. Reduced-motion rules reduce transitions/animations to .01ms and one iteration while content remains visible. Sidecar motion values record implementation, not the discarded proposed animation system.

## Shapes

Rectangular corners are small: tags/classifications 4px, controls 6px, panels 8px. Fine borders separate documents and ledger rows; strong borders identify fields and secondary actions. Pills are not the default silhouette. Tiny status dots and the spinner are functional exceptions. SVG icons use currentColor, a 1.5px stroke, round caps/joins and generally 16–20px sizing.

## Components

### Buttons

Primary submission: ink/white, 6px corners, 48px minimum height, 18px horizontal padding and 14px/550 type. Hover is charcoal; disabled opacity is .55. Secondary actions: white with a strong 1px border, 44px minimum height, 16px horizontal padding and 14px/500 type. Account navigation uses a compact 44px black variant. Original-source actions use 16px padding and weight 500. Preserve these actual role variants.

### Inputs / Fields

Persistent labels sit 8px above fields. Source search/select uses white, strong 1px borders, 6px corners, 48px minimum height and 16px text. Auth fields group the border around an input and optional 44px password toggle; search-with-submit places a borderless input and black action inside one frame. Composite focus outlines are 2px cobalt with 3px offset; standalone controls use the shared 4px offset. Errors stay adjacent to the form; disabled actions recede visibly.

### Navigation

The desktop shell aligns brand, central links and account actions in a 72px header. Links have 44px targets, secondary ink and a near-black hover/active state; active links use a quiet underline. Public navigation compacts after 56px scroll into an 840px white frame; application navigation stays stable. About uses a bordered white 8px menu. Company views use horizontal underline navigation, a 2px active ink rule and 52px desktop/48px mobile targets. Mobile focus behavior follows Layout.

### Chips / Tags

Ticker tags use neutral rectangles, 4px corners and 13px/550 type; clickable feed tags retain a 44px target and cobalt hover. Sentiment badges use 4px corners, 4px 7px padding, 13px/450 type, and semantic colour plus a visible label. Neutral classification uses the cool surface. Tags communicate identity/status rather than decorative metrics.

### Reading / Evidence Panels

The selected reader is a white, finely bordered 8px document with 32px desktop padding and 24px 20px mobile padding. Summary reading uses 28px 32px; unbordered stone evidence uses 28px. Title, attribution, original action and research sections form one document. Evidence follows the selected topic and moves inside it at narrower sizes. Citation links are underlined, wrap long titles and shift to cobalt on hover. Missing URLs have an explicit unavailable state.

### Feeds / Ledgers

Announcements form date groups in one white document. Metadata, complete title, excerpt and source/research actions stay together; fine dividers and 24px vertical padding separate records, then 20px below 640px. Search aligns ticker, identity, sector and available metric roles. One collection note replaces a wholly unavailable metric column. Stone trending/context rows use quiet rules and actual returned counts.

### Topic Disclosures / Contents

Native topic disclosures use ruled 68px headers, 18px titles, labelled classification and a small chevron; mobile headers are 64px. Open state changes the chevron direction and exposes 16px reading copy with related evidence/analysis details. History contents is a bounded sticky stone rail on desktop and a native collapsible control mobile. Pending analysis remains compact.

### Forms / Result States

Account forms use white 8px panels on stone; sign-in/signup add an introduction where space permits. Settings separates white preferences from stone delivery status. Results use one bounded white panel, restrained status icon, readable explanation and a clear next action. Semantic feedback, live/alert roles, native fields and existing account/token behavior remain intact. Style extraction does not certify every runtime branch.

The sidecar carries ten drop-in previews translated from these real components, with inherited variables, literal fallbacks and inline SVG. They need no React, CSS modules, icon package or image asset. Synthesized colour ramps are preview metadata, not application tokens.

## Do's and Don'ts

### Do:

- **Do** align major regions to the shared frame and choose a narrower measure for reading.
- **Do** keep metadata attached to its record and make the original-source action easy to locate.
- **Do** use white for reading, stone for evidence/context and cool neutral for tools.
- **Do** show pending, empty, unavailable and error states with honest, compact content.
- **Do** retain visible keyboard focus, persistent accessible names and a reduced-motion path.

### Don't:

- **Don't** add decorative photography, copied Quartr imagery or invented market figures to fill a composition.
- **Don't** turn every record or paragraph into a separate elevated card.
- **Don't** use cobalt or semantic green as a substitute for heading hierarchy or black primary actions.
- **Don't** hide substantive content behind global entrance animation.
- **Don't** let mobile controls or long titles exceed the viewport, or leave covered content keyboard-reachable.

Source authority: [page styles](frontend/src/app/page.module.css), [shell](frontend/src/app/components/layout/AppFrame.module.css), [company workspace](frontend/src/app/components/company/CompanyWorkspace.module.css), [research surfaces](frontend/src/app/components/research/ResearchSurface.module.css), [announcements](frontend/src/app/components/announcements/AnnouncementCard.module.css), [settings](frontend/src/app/settings/notifications/page.module.css) and [results](frontend/src/app/unsubscribe/page.module.css). See the [implementation record](docs/quartr-redesign-implementation.md) and [finish verdict](.impeccable/review/quartr-redesign/finish-verdict.md) for coverage and limitations.

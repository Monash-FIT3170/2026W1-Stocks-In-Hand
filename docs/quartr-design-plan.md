# Quartr reference study and StonksInHand design plan

Prepared 13 October 2026. Planning deliverable; the specifications below are proposed changes, not a record of an implemented redesign.

The objective is a coherent, premium research product with clear grouping, confident typography and purposeful use of horizontal space. The user-selected visual reference is Quartr. The app should keep its actual ASX content, source provenance, supported routes and account behaviour.

Read this document for the reference study, shared system and implementation sequence. Read the [page-by-page plan](quartr-page-by-page-plan.md) for every existing route, including the pages not yet rebuilt. [Evidence and measurements](design/quartr-study/README.md) documents what was inspected and what still requires verification.

## 1. What the reference establishes

The references are [Pricing](https://quartr.com/pricing), [Quartr API](https://quartr.com/products/quartr-api) and [Hedge funds](https://quartr.com/use-cases/hedge-funds). They are public marketing pages. This study does not claim to describe Quartr's authenticated application.

### Measured typography

These are computed browser styles at a 1280 × 720 viewport. Values belong to the named element, rather than a universal Quartr token. Animated headings can have duplicated text nodes; their visual heading was measured once.

| Reference and role | Size | Weight | Line height | Letter spacing |
|---|---:|---:|---:|---:|
| Pricing: page heading | 58px | 550 | 69.6px / 1.20 | −2.9px / −0.05em |
| Pricing: product panel heading | 19px | 550 | 26.6px / 1.40 | −0.57px / −0.03em |
| Pricing: comparison section heading | 38px | 550 | 41.8px / 1.10 | −1.52px / −0.04em |
| Pricing: product selector label | 13px | 450 | 18.2px / 1.40 | Approximately normal |
| API: hero heading | 48px | 550 | 50.4px / 1.05 | −2.4px / −0.05em |
| API: overview heading | 21px | 550 | 29.4px / 1.40 | −0.63px / −0.03em |
| API: audience section heading | 28px | 550 | 33.6px / 1.20 | −1.12px / −0.04em |
| API: dataset section heading | 38px | 550 | 41.8px / 1.10 | −1.52px / −0.04em |
| Hedge funds: hero heading | 48px | 550 | 50.4px / 1.05 | −2.4px / −0.05em |
| Hedge funds: feature section heading | 28px | 550 | 33.6px / 1.20 | −1.12px / −0.04em |
| Hedge funds: feature item heading | 19px | 550 | 26.6px / 1.40 | −0.57px / −0.03em |

The sampled elements use `InterVariable, Inter, …, sans-serif`. The page body defaults to 16px, weight 400. The perceived font variation is primarily a variation of roles within the same family.

### Measured composition

| Reference | Observable structure | Measurement |
|---|---|---|
| Pricing | Heading column beside two product panels | Three equal columns; 24px gaps |
| Pricing | Contained product content | 24px panel padding; 6px radius; 8px heading/text gap; larger 24px and 48px internal groups |
| Pricing | Spacious opening | Sample outer frame max-width 1328px, with 24px horizontal padding; 192px opening top padding |
| API | Hero and overview use coordinated columns | Twelve-column grids; 12px hero and 16px overview column gaps |
| API | Overview and evidence ledger share a row | Distinct text and facts regions; sampled section padding 96px vertically |
| Hedge funds | Feature groups occupy the row together | Repeated substantial modules with controlled text widths |

### Interpretation

The useful principles are scale contrast, close grouping, shared alignment, meaningful containment and varied composition. A broad section can contain a narrow text block. Pale panels and inverse backgrounds establish clear regions. Small radii and restrained borders keep the geometry precise. Photography supplies visual mass and warmth; our replacement must supply mass through real research content. These observations inform the proposals below; they do not prescribe identical marketing spacing for an application.

## 2. Diagnosis of our current implementation

The earlier changes improved organisation and removed excessive ticker decoration. They also made much of the research area a succession of similarly styled headings, rules, disclosures and grey text. It is possible to scan the rows while still struggling to distinguish the page's major regions.

### The font declaration is not the font implementation

`DESIGN.md` calls for Inter Variable. `components/layout/AppFrame.module.css` actually supplies `"Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial, sans-serif`. The root layout does not load Inter. On this Windows browser the measured family is the system stack. A specified weight of 550 is not proof that a real variable face supplies that weight.

This affects glyph shape, wrapping, heading density, perceived weight and the relationships between titles and controls. Font loading must precede final spacing decisions.

### Size is already excessive in some places

At the sampled 1280px viewport, home uses an approximately 95px heading and announcements uses 82px. The ticker view title is 36px, company identity 34px, section titles 24px and topic headings 15px. The contrast between route families is considerably larger than their difference in purpose requires.

Increasing all headings would deepen this inconsistency. The correction is a deliberate scale: moderate public display text, strong application titles, and readable topic/record headings.

### Widths exist, but compositions do not consistently use them

General pages use a 1240px outer frame with 32px padding, leaving 1176px of inner width at its maximum. The company workspace uses 1320px with 24px padding. Information pages cap at 820px; notifications cap at 1180px. Home has its own full-width geometry.

These are not inherently wrong widths. The problem is that they are not a named set of layouts. Related pages start on different alignment lines. Some views use a broad white area for a narrow paragraph and stretch small metadata across the rest. That reads as unused space, rather than a composed two-column page.

### Separation relies too often on a line

A horizontal rule can separate two records. Repeated rules cannot, by themselves, tell the user which content is a page introduction, an analysis chapter, a source collection or a secondary processing notice. Giving every section the same border treatment makes the levels equal.

### Supporting material is sometimes too prominent or too fragmented

Examples include the large announcements panel emphasising the count of six currently loaded records; the company quote, identity and view heading competing at similar weights; and evidence/model details requiring several nested disclosures. The feed's unconditional “Source monitor active” presentation is not demonstrated by the loaded record count. The design should distinguish a factual result count from a measured operational status.

### Sparse backend content exposes the layout

The current database includes records with pending summaries, unclassified facts and incomplete analysis. These are normal product states. A design dependent on a completed paragraph in every region will look empty under real data. Pending records need a purposeful compact presentation with their original material available immediately.

### CSS ownership is fragmented

`page.module.css` contains shared controls, multiple route styles, replacement rules and a legacy layer. Research and company modules add their own scales. Settings and transactional pages repeat replacement/legacy patterns. Another layer of overrides would increase uncertainty. The implementation should migrate complete component responsibilities into the shared system, then remove superseded visual rules after their consumers move.

## 3. The proposed visual direction

The direction is an editorial research workspace: neutral surfaces, precise Inter typography, broad compositions, controlled prose and substantial evidence modules. The product should feel finished because each region has a clear purpose, not because every screen has elaborate decoration.

### Six governing rules

1. **Give each screen one clear centre of attention.** A filing brief, an announcement feed, a company directory or a form should dominate its supporting material.
2. **Use distance to describe relationships.** Titles sit close to their descriptions; independent sections receive larger gaps.
3. **Assign width to a task.** Analysis, record selection, provenance, controls and contextual facts have distinct columns when they coexist.
4. **Create surface boundaries by purpose.** A reading surface, a settings group and a source panel deserve different treatment. Every paragraph does not deserve a card.
5. **Preserve useful density.** Premium research UI should reveal useful content promptly. Marketing-scale empty space does not belong between every analysis section.
6. **Let real material provide the visual weight.** Company identity, a source-backed brief, a document descriptor or a factual ledger supplies a focal region without photography.

### Where expression belongs

| Surface | Main character | Degree of expression |
|---|---|---|
| Home and About | Introduce the product and workflow | Strongest composition; restrained feature exhibits |
| Announcements and Search | Browse and select | Wide, clear, efficient; compact supporting context |
| Company summary and Deep dive | Read and verify | Editorial hierarchy; comfortable prose and evidence |
| Source records | Select a document and inspect it | Strong index/reader distinction; clear selection |
| Watchlist | Monitor saved companies | Consistent company modules; visible update state |
| Account and alert settings | Complete a task | Quiet, contained controls; explicit feedback |
| Terms and transactional results | Understand a document or outcome | Deliberately limited reading width |

## 4. Typography specification

These are recommended StonksInHand values. They are not claimed Quartr measurements. Use rem-based implementation so browser text sizing remains effective. Desktop refers to a roomy layout, not every viewport above a single breakpoint.

| Role | Desktop | Tablet | Mobile | Weight | Line height | Tracking |
|---|---:|---:|---:|---:|---:|---:|
| Public home display | 64px | 52px | 38px | 550 | 1.05–1.10 | −0.045em |
| Public information page title | 52px | 44px | 34px | 550 | 1.10 | −0.04em |
| Browse page title: search/feed/watchlist | 44px | 38px | 32px | 550 | 1.10 | −0.035em |
| Company identity | 40px | 34px | 28px | 550 | 1.15 | −0.035em |
| Research view title | 32px | 30px | 26px | 550 | 1.20 | −0.03em |
| Major research/feature section | 28px | 26px | 24px | 550 | 1.20 | −0.025em |
| Selected source / history entry title | 28px | 25px | 22px | 550 | 1.25–1.35 | −0.025em |
| Announcement title | 22px | 21px | 20px | 550–600 | 1.30 | −0.02em |
| Company/feature card title | 20px | 20px | 19px | 550 | 1.30 | −0.02em |
| Topic or minor subsection title | 18px | 18px | 18px | 550–600 | 1.35 | −0.01em |
| Auth/settings/result title | 34px | 32px | 28px | 550 | 1.15 | −0.03em |
| Introductory paragraph | 18px | 18px | 17px | 400 | 1.50 | Normal |
| Research prose | 16px | 16px | 16px | 400 | 1.60–1.65 | Normal |
| Compact supporting text | 14px | 14px | 14px | 400 | 1.50 | Normal |
| Publisher/date/status metadata | 13px | 13px | 13px | 400–500 | 1.40 | Normal |
| Field and action label | 14px | 14px | 14px | 500–550 | 1.40 | Normal |
| Exceptional footnote | 12px | 12px | 12px | 400 | 1.50 | Normal |

### Font loading and numeric treatment

- Load one actual Inter variable WOFF2 face at the root, preferably a locally stored font through `next/font/local`. Keep the font's licence alongside the asset. The official [Inter documentation](https://rsms.me/inter/) describes variable weights, optical sizing and tabular numerals; [Next.js font guidance](https://nextjs.org/docs/app/getting-started/fonts) documents self-hosting and local font loading.
- Use the resulting font variable throughout the app, including controls. Verify the loaded face in the browser rather than checking a CSS string alone.
- Use weights 400, 500, 550 and 600 as the normal vocabulary. Reserve stronger emphasis for a short important fact; avoid making every label semibold.
- Use tabular numerals for aligned prices, percentages, counts and times. Most numbers should remain Inter. Monospace is reserved for short ticker symbols and technical identifiers.
- Prefer actual italic styling only where content calls for it. Coloured words in a headline should not become the product's primary hierarchy mechanism.
- Do not apply display tracking to body text, dates, field labels or buttons.
- A long company or document title may wrap. Reduce size only through the defined responsive role, rather than shrinking individual long titles into tiny text.

### Heading semantics

Each route needs one clear H1 and a consistent outline. A title's visual size is independent of its HTML level. For ticker routes, keep the active view as the H1 and present the shared company identity as a prominent labelled identity block; use H2 for its major sections and H3 for topics. This avoids a shared H2 preceding the page's H1 while retaining a visually strong company name.

## 5. Width, grid and horizontal composition

### Shared frame

Use a **1360px maximum outer frame**, including its padding. Align global navigation, page headers and the full public footer to this same frame.

| Viewport class | Outer frame | Horizontal padding | Typical column gap |
|---|---|---:|---:|
| Desktop, 1200px and above | Width 100%, max 1360px | 32px | 24–32px |
| Tablet, 768–1199px | Width 100% | 24px | 24px |
| Mobile, below 768px | Width 100% | 16px | 16px after stacking |

At a 1440px viewport without a scrollbar, this produces 1296px of inner width and 72px from the viewport edge to the main alignment line. At 1280px, the inner width is 1216px. Actual browser scrollbar width reduces these figures slightly.

The change from 1240px to 1360px is modest. The major improvement comes from assigning that width to coherent regions. A 1920px display should not stretch research paragraphs to 1856px.

### Named compositions

| Composition | Primary use | Wide layout | Behaviour when space is insufficient |
|---|---|---|---|
| Introduction + exhibit | Home, About | Approximately 7/12 text and 5/12 real product exhibit | Intro and primary action, then exhibit |
| Reading + evidence | Ticker summary | Approximately 8/12 analysis and 4/12 evidence/context | Evidence follows the analysis it supports |
| Feed + context | Announcements | Approximately 8/12 records and 4/12 existing trending/context | Compact context strip, then feed |
| Index + reader | Source records | Approximately 4/12 index and 8/12 reader | Select/read drill-down within one page |
| Contents + document | Deep dive, Terms | Narrow contents column and generous document column | Collapsible contents above the document |
| Repeated company modules | Watchlist | Three substantial columns; two at intermediate widths | One column, no fake empty slots |
| Explanation + form | Signup/signin where useful | 360–420px introduction; 420–460px form | One form sequence |
| Task form + status | Alert settings | Approximately 2/3 rules, 1/3 delivery status | Verification summary before form; details after |

### Reading widths

- Research prose: preferred 64–72ch; evaluate actual line length after Inter loads.
- Page introductions: 48–62ch.
- Record excerpts: 58–70ch; headlines may use the wider primary column.
- Supporting evidence descriptions: 32–45ch.
- Forms: fields generally no wider than 520px unless the content warrants it.
- Terms: a centred document assembly around 1024px, containing a contents column and a 680–752px reading column.

Do not add a secondary column merely to occupy space. When supporting content is absent, let the primary region expand within its intended reading layout. Short content does not justify invented metrics or a repeated explanation.

## 6. Spacing and separation

### Spatial vocabulary

Use a base scale of 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80 and 96px. Name the relationships rather than choosing a new number for each selector.

| Relationship | Desktop | Mobile |
|---|---:|---:|
| Metadata pieces within one line | 8–12px | 8px, wrapping naturally |
| Label to field / title to immediate description | 8px | 8px |
| Record title to excerpt | 12px | 10–12px |
| Paragraph to paragraph | 16px | 16px |
| Description to actions | 16–20px | 16px |
| Separate groups inside a panel | 24px | 20–24px |
| Default panel padding | 24–32px | 20px |
| Reader padding | 32px | 20px |
| Page title/intro to work area | 32px | 24px |
| Major app section to next major section | 40–48px | 28–32px |
| Major public-page chapter | 80–96px | 48–56px |
| Top of application page below navigation | 40–48px | 28–32px |
| Top of public introduction | 72–96px | 40–48px |

The section gap must visibly exceed the title/body gap. A useful starting ratio is roughly three to one. Final values should reflect content density rather than an arbitrary rule that every group needs 96px.

### Separation vocabulary

Use the smallest treatment that conveys the correct level:

1. **Proximity:** a title, description and actions form one unit.
2. **Whitespace:** independent topics receive a larger gap.
3. **Surface:** tools, evidence and a selected document have a recognisable region.
4. **Rule:** chronological entries or ledger rows receive a quiet boundary.
5. **Type:** a chapter heading differs clearly from a minor field label.

Do not apply all five treatments to every unit. A major region should usually have two complementary signals. For example, a surface plus a strong heading identifies the source reader; spacing plus a date rail identifies a history entry.

Avoid stacked horizontal lines around a heading, a toolbar, a count, a row and a disclosure when a single enclosing region would communicate the same relationship.

## 7. Surface, colour and shape

### Proposed palette

Retain the existing near-black ink and cobalt identity. Add a neutral stone surface for contextual groups so the product can have warmth without photography. Blue should express interaction, not wash over every region.

| Token | Proposed value | Use |
|---|---|---|
| Canvas | `#fbfcfc` | Page background |
| Reading surface | `#ffffff` | Main document, forms and selected reader |
| Context surface | `#f3f2ef` | Evidence/context bands; occasional public exhibit |
| Control surface | `#f4f6f8` | Quiet toolbars and secondary states |
| Primary ink | `#101214` | Headings, prose and primary actions |
| Secondary ink | `#4e5965` | Explanations and supporting prose |
| Metadata ink | `#626a73` | Dates, publishers and minor labels |
| Decorative line | `#dfe4e8` | Section/record boundaries |
| Functional boundary | `#818991` | Inputs and essential control outlines; at least 3:1 on the proposed light surfaces |
| Brand/focus | `#2f5bea` | Focus, selected state and restrained links |
| Selected wash | Existing `#e9eeff` | Selection with an additional non-colour signal |
| Inverse surface | `#101214` | Limited public exhibit or a meaningful compact feature |

A contrast calculation confirmed the existing primary ink at 18.77:1 and secondary ink at 7.14:1 against white. Against the proposed stone surface they are 16.77:1 and 6.38:1 respectively. An initial candidate metadata colour `#697078` failed narrowly on stone at 4.48:1, so it is not the proposed metadata token. The chosen `#626a73` metadata colour is 5.49:1 on white and 4.90:1 on stone. The functional boundary is 3.55:1 on white and 3.17:1 on stone. These calculations are saved in the [proposed palette check](design/quartr-study/proposed-contrast-check.json); rendered combinations still require implementation verification.

Keep positive, warning and negative colour attached to their actual meaning. The existing amber text is not suitable for small text on every neutral surface; use `#8a5b00` for warning text where it appears on the proposed neutral surfaces, and verify warning-soft pairings separately. Classification badges must include a text label. A green price movement is not interchangeable with positive filing classification.

### Surface roles

- **Main reading surface:** one recognisable region, with generous internal padding. It may have a quiet edge when the surrounding canvas is visible.
- **Evidence surface:** a stone or control surface, a short title and structured source descriptors. It should read as the companion to analysis.
- **Controls:** a compact neutral strip. Its height and density identify it as a work tool.
- **Featured public exhibit:** one dark or neutral module with real product content. It does not repeat on every application section.
- **Status:** a small attached notice unless the whole task failed. Pending data should not become a giant empty hero.

### Geometry

Default controls: 6–8px radius. Standard grouped panels: 8–12px. Major public exhibits: up to 12px. Use pill geometry only for a compact filter/status where it helps recognition. Do not use 16–20px rounded containers everywhere.

Use 1px decorative rules and edges. Shadows belong mainly to menus, popovers and modal overlays; static records should not float above the page. Input boundaries and focus states must remain sufficiently visible even when decorative borders are very light.

## 8. Components and interaction specification

### Page header

One component supports public, browse and task variants. It owns title/description spacing, optional supporting count, and an action slot. Long descriptions should not force an action into a narrow sliver. On mobile, description and count belong below the heading rather than beside it.

### Section heading

It owns heading, optional explanation and an optional quiet action. Explanations sit 8–12px below the title. The space before the section is substantially larger. A contextual eyebrow is optional, not mandatory on every group.

### Record row

Order: source identity/date → title → substantive excerpt → primary/supporting actions. Use stable alignment lines and clear internal grouping. Metadata is 13px, title 20–22px and excerpt 16px. An original-source link should be visible without expanding model details.

Missing excerpts produce shorter rows. Do not fill them with generic investment language. Natural wrapping is preferred to cutting meaningful titles. Repeated identical excerpts should be suppressed using the existing presentation helpers.

### Source descriptor

Keep document kind, publisher, date and original-link action together. A title may use one or two lines, with accessible full text when a compact index truncates it. The selected reader always displays the complete title. Deduplicate source URLs using existing helpers. “Source unavailable” is a truthful state, not an empty disabled button pretending a URL exists.

### Evidence panel

It has a heading, a short scope statement when necessary, and source descriptors or a factual ledger. Use one panel for the currently relevant analysis. Per-topic citations must remain connected to that topic; do not collect every topic's links into an unrelated global list.

### Fact ledger

Use aligned labels and tabular values. Values can be 20–24px when they are meaningful facts; processing counts should remain smaller. Avoid equal-sized metric tiles for every available field. Two to four useful facts can occupy a horizontal row; they should not become miniature promotional cards.

### Disclosures

Use disclosures for secondary detail, not to hide the core product. Topic labels need 18px text and sufficient hit area. The first available topic may begin open. Model name/confidence and processing metadata can remain behind one analysis-details disclosure. Original material stays directly accessible.

### Buttons and links

Primary action: near-black fill, white text, 14px/550, 44–48px height, 6–8px radius. Secondary: white/transparent with a visible boundary. Tertiary: text link with a clear underline or other persistent affordance.

The page may have one dominant task action. Repeated “Open original” links inside a feed should not all become large black buttons. Within a selected reader, the original link can be the principal action. Reuse labels consistently across ticker and feed views.

Quartr's sampled sales buttons were 36px high. Our touch targets should retain a minimum 44px hit area; copying a smaller visual control is not necessary to achieve the same precision.

### Forms

Visible labels, 48px input height, 16px input text and 8px label/field spacing. Field groups are separated by 20–24px. Errors belong adjacent to the affected field where the existing error data permits; a form-wide error still has a clear summary. Reserve stable room for submission feedback without a huge blank area.

Checkbox/switch controls retain native semantics. Changing appearance must not alter submission, disabled, verification or authentication logic. Confidence controls refer to classification confidence, not predicted investment performance.

### Icons

Reuse the app's SVG vocabulary, normalising size and stroke. Typical sizes: 16px metadata, 18–20px actions and 24px feature indicators. Use text labels for unfamiliar functions. Inspect the search and password-toggle icons: current captures show dot-like shapes in places where a recognisable search or visibility symbol is intended.

### Navigation and footer

Align navigation with the shared frame. Keep direct access to company search and market feed. Watchlist/account access depends on existing auth state. Public information destinations can remain in a compact grouped menu; the app does not need a large marketing mega-menu for a handful of routes.

The existing floating compact nav can be retained only if it preserves destination visibility, reading position, keyboard focus and the app's identity. A fixed, calm application header is an acceptable task-oriented variant. Do not introduce a navigation transformation simply because it appears on the reference.

Use the full directory footer on public pages. Application pages can use a smaller footer with the same source/terms links, so a large promotional footer does not dominate a short error or research state.

## 9. Motion and perceived quality

The reference visibly uses heading and content entrances, but this study did not measure every animation duration. The following are our recommended timings:

| Interaction | Timing | Behaviour |
|---|---:|---|
| Link/control hover | 150–180ms | Colour/border feedback; no repeated lift |
| Button press | 100–140ms | At most a subtle 1px press |
| Menu/popover | 180–240ms | Small translation plus opacity |
| Reader selection | 160–220ms | Subtle continuity; preserve usable content |
| Public intro entrance | 300–450ms | Optional one-time restrained entrance |
| Application data refresh | Immediate content feedback | Avoid animating every row on every response |

Use the existing ease-out curve for expressive transitions and a simpler utility curve for controls. Avoid blur entrances on essential research content, scroll-jacking, endlessly staggered records and delayed action availability. Reduced-motion users receive the final layout immediately. Loading indicators must describe actual loading, not create artificial suspense.

## 10. Responsive rules

The desktop reference values are measured. Mobile values in this plan are our recommendations. Current app captures include confirmed 390 × 844 layouts; a complete reference/mobile and implementation breakpoint review remains a validation task.

- Below roughly 1100px, test whether analysis/evidence columns still support their minimum useful widths. Stack based on content fit rather than preserving a nominal desktop grid.
- Below 768px, use the mobile frame and navigation. Company modules move to one column when two would make their titles or actions cramped.
- Below roughly 700px, source selection becomes a drill-down presentation, and history contents become a compact disclosure.
- Keep at least 16px input text and 44px touch targets.
- A supporting rail must not become a large block that pushes all useful primary content below the first screen.
- Reading order should follow the task: identity → view → primary content → relevant evidence → processing detail.
- Sticky elements need a known top offset and must not collide with each other. Chapter anchors and focused controls need a corresponding scroll margin.
- At 200% text zoom, columns and toolbars must reflow; do not clip them with `overflow: hidden` as a repair.
- Test long company names, multi-line document titles, date labels, missing quote fields and long original-source domains.

## 11. Data and behaviour constraints

The [ticker API contract](ticker-rebuild-contract.md), existing API helpers and data formatting functions remain the factual authority. The redesign is not permission to invent a richer backend.

| Proposed design material | Existing support | Constraint |
|---|---|---|
| Company identity, sector, latest available quote | Existing brief/overview fields | Do not call a quote live or add an as-of time without a field |
| Six topical analyses | Existing category endpoint | Keep topic-specific availability, classifications and citations |
| Source index/reader | Existing up-to-ten record collection | Do not imply a complete archive |
| Research history | Existing up-to-ten persisted entries | Do not imply an exhaustive company history |
| Market feed and date/sector filters | Existing announcements helpers | Preserve query parameters and pagination |
| Trending context | Existing seven-day activity result | Activity is not investment performance or popularity |
| Saved-company modules | Existing watchlist flow | Preserve account ownership and add/remove behaviour |
| Alerts rules and delivery state | Existing preferences endpoint | Preserve feature flag, verification and saving states |
| Time-series charts, automated change comparisons, document images | Not established by this study | Separate capability work if needed; no invented display data |

Do not sum category source counts and label the result as unique documents. Do not promote model confidence to an investment score. Do not show “monitor active” based solely on having fetched some records. On sparse pages, lead with what is available and show missing analysis plainly.

## 12. Implementation architecture and migration

### Shared building blocks

Create a small set of genuinely reused primitives: `PageFrame`, `PageHeader`, `SectionHeading`, `Surface`, `Action`, `MetadataLine`, `SourceDescriptor`, `EvidencePanel`, `FactLedger`, `ResourceState` and `AuthPanel`. Names are proposed; they should be adjusted to the repository's conventions.

Do not turn every content arrangement into a generic component with dozens of flags. Route-specific compositions belong in their route modules. Shared primitives own the type, spacing and surface roles that are currently drifting.

### Source ownership

| Responsibility | Current location | Migration |
|---|---|---|
| Font loading | `frontend/src/app/layout.jsx` | Load Inter once and publish the font variable |
| Tokens and shell | `components/layout/AppFrame.module.css` | Centralise shared tokens/frame and shell variants |
| Shared page rules and legacy styles | `frontend/src/app/page.module.css` | Move active primitives and route styles to clear owners |
| Feed region styles | `components/research/ResearchSurface.module.css` | Apply feed/context composition and shared roles |
| Announcement presentation | `components/announcements/AnnouncementCard.*` | Retain presentation helpers; update composition |
| Company views | `components/company/*` | Keep data hooks; rebuild reading/evidence arrangements |
| Auth fields | `components/auth/AuthField.jsx` | Retain semantics; use shared form roles |
| Alert settings | `settings/notifications/*` | Use task-form/status composition |
| Transactional results | `unsubscribe/page.module.css` and consumer | Use shared result-panel roles |
| Visual documentation | `DESIGN.md` and surface docs | Replace contradictory specifications after direction is implemented |

A temporary compatibility mapping can keep existing token aliases working while pages migrate. It should have an explicit removal point. Aliases such as `--green` currently mapping to cobalt are a maintenance aid, not the new semantic vocabulary.

### Delivery sequence

1. **Foundation and representative compositions.** Load Inter, establish the frame/type/spacing/surface tokens, and prepare real-content comparison layouts for announcements and one company summary. These two screens prove the system under browse and read tasks.
2. **Company workspace.** Apply the shared identity/header/nav and the three distinct summary, source-reader and history compositions. Validate complete, pending and unavailable data.
3. **Market browsing.** Bring announcements and search onto the same header and record system. Preserve feed features while rebalancing their emphasis.
4. **Personal workspace.** Migrate watchlist, add-company modal and notification settings. Validate authenticated states with an authorised test session or controlled fixtures.
5. **Public pages.** Recompose home and About with actual product exhibits; update source directory and Terms using reading layouts.
6. **Account and result flows.** Apply the shared form/result system to all account, verification, unsubscribe and not-found states. Preserve security behaviour.
7. **Consolidation.** Remove superseded style rules, update design documentation and complete cross-route visual/interaction verification.

Each step should produce a complete route family rather than a superficial stylesheet overlay. The current approved changes and unrelated repository files must remain recoverable throughout migration.

## 13. Acceptance criteria

### Visual comparison

Use fixed viewport captures of our app and the selected public references. Compare the design qualities, not the amount of photography. Use representative real content and record the viewport and data state with every screenshot.

| Dimension | Evidence required |
|---|---|
| Typography | Inter actually loaded; consistent roles; legible prose and metadata; no oversized app hero competing with the work |
| Separation | Major regions identified by at least two useful signals; tight internal grouping and clearly larger external gaps |
| Horizontal use | Columns carry meaningful content; broad frames do not produce broad paragraphs or empty filler columns |
| Composition | One primary region per view; supportive material is clearly subordinate |
| Surface/contrast | Reading, tools and evidence are distinct; controls and text pass their contrast requirements |
| Detail | Consistent icons, baselines, radii, action alignment and date/publisher formatting |
| Real-data resilience | Pending, short, long, empty, partial-error and unavailable states look deliberate |
| Consistency | Shared identity persists across all twenty route patterns, not only the flagship pages |

Evaluate each dimension on a documented 1–5 scale: 1 = broken, 2 = visibly inconsistent, 3 = usable but weak, 4 = coherent and polished, 5 = particularly strong. Aim for at least 4 throughout and no unresolved 1/2 finding. The scale is an internal review aid, not an objective claim that beauty has been numerically proven.

### Practical checks

- Visual coverage at 375/390, 768, 1024, 1280/1440 and a wide desktop; 200% text zoom.
- Header, footer and route frame alignment across every route family.
- Keyboard navigation, visible focus, disclosures, source selection, jump/return behaviour and modal focus.
- Search submission, filter reset, pagination, preserved query parameters and valid company links.
- Watchlist ownership/add/remove, alert disabled/dirty/saving states and auth redirects.
- Stable loading layout without replacing known identity with misleading default data where it can be preserved.
- Normal text contrast of at least 4.5:1; large text and essential non-text UI at least 3:1; no colour-only meaning.
- Reduced-motion behaviour and no invisible essential content when entrance effects fail.
- Appropriate frontend lint, existing tests and production build; additional tests only where behaviour changes merit them.

### Review boundaries

Perform a complete first pass, consolidate the identified changes, then confirm the fixes in a second pass. If a material issue remains, document it and resolve that issue; avoid drifting into an endless sequence of unrelated micro-adjustments. The user-selected Quartr direction stays the reference during every pass.

## 14. Recommended first implementation slice

Start with the real Inter font, one frame, the shared type scale, and the new announcements/summary compositions. Include both a substantive analysis and a pending-summary record. This slice should demonstrate all four missing qualities together: stronger hierarchy, meaningful separation, natural horizontal coverage and a substantial focal area.

A font-only update, more blank padding or a wholesale return to identical cards would not fulfil this plan. The expected result is a visible change in how the information is read and related, carried consistently into the remaining routes.

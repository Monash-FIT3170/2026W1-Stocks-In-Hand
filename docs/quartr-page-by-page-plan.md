# Page-by-page design plan

Companion to the [Quartr study and shared design system plan](quartr-design-plan.md). Prepared 13 October 2026. All layouts and sizes here are proposals. Existing data, routes, authentication and account behaviour remain the implementation constraints.

The shared plan defines typography, colour, spacing, widths, responsive behaviour and acceptance criteria. This document applies those decisions to each existing route rather than treating the ticker and announcements pages as isolated redesigns.

## 1. Complete route coverage

There are twenty existing page route patterns, including the three ticker views. The not-found boundary and shared shell are additional surfaces.

| Route | Job | Proposed composition | Inspection basis |
|---|---|---|---|
| `/` | Start company research | Introduction + real product exhibit | Rendered desktop and source |
| `/search` | Find a supported company | Search header + company ledger | Rendered mobile and source |
| `/announcements` | Scan and verify market records | Feed + context | Rendered desktop and source; previous feed audit |
| `/ticker/[symbol]` | Understand current company research | Analysis + evidence | Rendered COH desktop and source |
| `/ticker/[symbol]/news` | Inspect a collected source | Index + selected reader | Rendered COH mobile and source |
| `/ticker/[symbol]/deep-dive` | Read research history | Contents + dated document | Rendered COH mobile and source |
| `/watchlist` | Monitor saved companies | Repeated company modules | Initial unauthenticated/loading render; authenticated layout reviewed in source |
| `/settings/notifications` | Configure watchlist alerts | Rules form + delivery status | Source; requires authenticated state for full visual validation |
| `/about` | Understand the product | Introduction + workflow | Rendered mobile and source |
| `/data-sources` | Understand source types and limitations | Source directory | Rendered mobile and source |
| `/terms` | Read existing terms | Contents + reading column | Rendered mobile and source |
| `/sign-in` | Access an account | Compact form / restrained split | Rendered mobile and source |
| `/sign-up` | Create an account | Introduction + form | Rendered mobile and source |
| `/forgot-password` | Request a reset code | Compact task form | Source |
| `/reset-password` | Submit code and new password | Compact task form | Source |
| `/confirm-sign-up` | Confirm an account email | Compact code form | Source |
| `/mfa-setup` | Set up an authenticator | Step-oriented task panel | Source |
| `/sign-out` | End session and return home | Transient status only | Source; not visited because navigation performs sign-out |
| `/verify-notifications` | Confirm alert email | Transactional result | Source; shares result styling |
| `/unsubscribe` | Turn off alerts from an email link | Transactional result | Rendered missing-token state and source |
| Not-found boundary | Recover from unsupported address | Compact recovery panel | Source |

Authenticated success states and token-driven results were not executed just to collect screenshots. The plan covers their actual branches in source; implementation validation should use an authorised session or fixtures and explicitly distinguish those checks from public-page browsing.

## 2. Shared shell: navigation, alignment and footer

### Intended result

Every route should feel like a deliberate room in the same product. Moving from the market feed to a company, then to a source and back to search should not change font family, page edge, control geometry or the meaning of emphasis.

### Desktop

- Use the shared 1360px outer frame for navigation and page alignment.
- Keep the brand at the left, research destinations in the centre and account actions at the right. Primary links retain a 44px hit area with 14–15px type.
- Prefer direct research labels such as Search and Market feed over a large generic Product menu for the current small route set.
- Keep About/Data sources/Terms grouped using existing destinations and short labels. A menu should have enough structure to be understandable, without invented promotional content or photographic tiles.
- Active routes need a persistent non-colour indicator, such as stronger type plus an underline or restrained selected surface.
- The compact floating state, if retained, must not obscure a page's local navigation or erase destination labels. Shared research screens may use a stable header variant instead of copying a public-site animation mechanically.

### Mobile

- Retain the existing mobile panel behaviour, accessible name, Escape handling and focus return.
- Keep the brand and menu action on one line. Use a 44px menu hit area even if its visible icon is smaller.
- Separate research destinations, information links and account action with meaningful group spacing. Avoid turning each into an unrelated oversized card.
- The opened panel must scroll on short screens; account actions should remain reachable when text is enlarged.

### Footer

Public pages get a directory footer with one short product statement and the existing research/company destinations. Application and task pages get a compact footer variant with the same important source/terms destinations available. This prevents the footer becoming the most visually dominant part of an empty result or short form.

## 3. Home — `/`

### Current issue

The existing approximately 95px desktop headline and decorative rings consume almost the entire first viewport. The page has visual intensity, but the right side does not explain the product. The three features below it are modest text groups whose visual weight drops abruptly.

### Proposed composition

Use a 7/5 introduction-and-exhibit layout. The introduction contains the headline, current factual description, company search and supported ticker links. The companion exhibit shows the research workflow or one actual supported source/brief. A dark surface can remain, but its composition should be driven by content.

```text
shared navigation

headline and description     | source-backed product exhibit
company search              | company → brief → original source
supported ticker links      | a substantial, purposeful region

three substantial feature groups
source-first workflow / next useful action
public footer
```

### Detailed specification

- Display title 64px/550, about 1.05–1.10 line height; mobile 38px. Limit the text to a deliberate two/three-line composition instead of stretching it to the outer frame.
- Introduction 18px, maximum roughly 56ch. Leave 24px to search; ticker links follow at 16–20px.
- Search field remains explicit and functional. Use a recognisable search SVG, 16px field text and 48px control height. Keep the primary submit action visibly part of the field group.
- Remove the decorative ring/radial treatment when the product exhibit replaces it. Do not keep both as competing focal regions.
- The right exhibit can use an actual source descriptor and a short, source-backed analysis from existing helpers. Its content must carry a clearly identified company and original link.
- If no suitable data is available, use a truthful workflow exhibit that describes the existing collection → summary → original-source process. It should have no fabricated quote, performance chart or invented financial paragraph.
- Three feature groups use 20px headings, 16px descriptions and 24px gaps. A neutral content exhibit or small diagram can give each group mass; three identical icon bubbles alone will not replace the photographic weight of the reference.
- Use 80–96px between public chapters, not between every element in the hero.

### Mobile and states

Put search before the exhibit. Keep the first useful action visible promptly. Ticker links wrap in a small group; do not horizontally scroll them unless there is a deliberate navigation reason. API failures should affect the data exhibit/ticker group rather than replace the whole introduction.

The current headline contains broad coverage/speed wording. A design pass should not strengthen those claims. Any wording review must match supported coverage and measured behaviour.

## 4. Search — `/search`

### Current issue

The page separates its search field from the heading by a large gap, then repeats relatively large cards. On mobile, the result count appears in a narrow column alongside the heading and becomes awkwardly stacked. The desktop row mixes small metadata, company name, industry and metrics without a stable visible hierarchy.

### Proposed composition

Make the search header one region: page title, short count/status and search form. Under it, present a broad, aligned company ledger. A result's company identity is primary; sector/industry and the actual available market cap are secondary.

```text
Browse/search title           result count
search field + submit

ticker | company name + industry | sector | available market cap
ticker | company name + industry | sector | available market cap
```

### Detailed specification

- Browse title 44px, mobile 32px. Count/status 14px, below the title on mobile.
- Place the form 20–24px below the introduction and the ledger 32px below the header region.
- Desktop result identity: 20px/550 company name; 14px industry line; 13px ticker/metadata. Avoid putting a large blank area between the title and its industry.
- Use stable columns: compact ticker, flexible company/industry, sector and right-aligned market cap. Allocate width according to the data, not four equal columns.
- A result can remain a navigable list item using the current Link behaviour. If implemented as a semantic table, keep valid table markup and explicit company links rather than placing anchors around table rows.
- Optional visual column labels are 13px and must match labels accessible to assistive technology.
- Rows receive 16–20px vertical padding and a quiet boundary. Hover changes surface or border without lifting every row.
- Missing market cap stays a plainly labelled unavailable value. Do not give it the same visual prominence as a useful reported metric.

### Mobile and states

Each row becomes a compact stacked identity group: ticker/sector → company → industry → available metadata. Use the full readable width; the count never sits in a narrow side column. Empty results offer the existing broader-search suggestion; a network failure shows a distinct retry state. Loading rows reserve approximate row geometry.

The current client-side search operates on the returned limited ticker collection. The redesign must not imply a complete exchange-wide search or link to unsupported static ticker routes. Expanded coverage is separate backend/routing work.

## 5. Announcements — `/announcements`

### Current issue

The top area already has useful visual grouping, and the user likes some of it. The main feed still reads as repeated open text on almost the same background. The 82px headline and large six-record count panel receive disproportionate attention. The latest source region needs a stronger identity and tighter internal relationships.

### Proposed composition

Retain the existing hero concept, filters, trending data, source types and pagination. Rebalance the header and compose the feed beside useful context. The main records become the first clearly dominant work area.

```text
page title + concise description       current filter/result scope
full-width filter toolbar

Latest source records                  Trending this week
date group                             existing activity results
  source/date → title                  source guide link
  excerpt → original/company actions
date group
  next records
show more
```

### Detailed specification

- Page title 44px desktop, 32px mobile, with an 18px introduction. Keep its wording unless a separate clarity correction is needed.
- Reduce the header's vertical cost. Do not transplant the reference's 192px marketing opening gap into a daily research feed.
- Keep a compact scope/status region if useful. Six loaded records is a view count, not a coverage achievement. Show it beside the feed heading or as restrained scope metadata.
- The existing dark pulse-panel treatment can be repurposed only around meaningful actual data. Remove or qualify the unconditional active-monitor claim unless real operational state backs it.
- Keep a full-width neutral filter strip with 48px fields, 14px labels and clear reset. Avoid the existing 10/11px helper labels where they carry essential meaning.
- Main feed occupies roughly eight columns; existing trending/context occupies four on a roomy desktop. If there is too little context to justify a rail, retain trending as a compact full-width strip and use a single deliberate reading region below it.
- Use one white feed region over the canvas. Date groups and record boundaries establish its internal rhythm; individual paragraphs are not nested cards.
- “Latest source records” uses 28px. Date headings use 16–18px medium weight. Record titles use 22px desktop/20px mobile; descriptions use 16px.
- Group metadata at the top of the record: ticker if supported, source kind, publisher and date. Maintain stable alignment without separating one metadata field to a distant edge unnecessarily.
- Record padding 20–24px; title-to-excerpt 12px; excerpt-to-actions 16px; larger space between date groups.
- Original-source and company actions remain directly visible. Secondary analysis can stay in one quiet disclosure.

### Mobile and states

Compact filters can be disclosed, but current scope and reset remain visible. Trend context should not occupy a large block before any record. Source descriptions wrap naturally. Pending analysis produces a shorter record containing its real title, date and original link.

Group by the original publication timestamp in Australia/Sydney. “Today” and “Yesterday” are only used when the timestamp actually matches those local dates. Invalid dates use an explicit undated group; do not group by a guessed date from the formatted display string.

Preserve source URL safety/deduplication, the pending state for summary lines the API sends as null, supported-ticker gating, query parameters and show-more pagination. Keep generic ASX records market-wide rather than linking to an unsupported `/ticker/ASX` route.

## 6. Shared company identity and local navigation

### Current issue

The company name and the view heading are nearly equal in scale. Quote, update date and watchlist link are spread across a flat header, while the view navigation is another thin ruled row. The header feels assembled rather than composed.

### Proposed specification

- Shared frame; 24–32px vertical identity padding.
- Desktop company identity 40px/550. Ticker is a small neutral/mono label, sector and latest source date are 13–14px metadata.
- Quote sits in a compact factual group: a quiet label, 24–28px tabular value and 13px movement text. Do not reintroduce the same price in every subsequent ledger.
- “Open watchlist” remains a navigation action. It is not an add-to-watchlist action and should not use a misleading plus/save label.
- Arrange identity, quote and action in purposeful groups with 24–32px separation. The quote does not require a giant metric tile.
- Local navigation gets a visually distinct 48px region with a persistent active indication. It should be clearly related to the company header and clearly separate from the reading surface.
- Active view title is 32px/550. It introduces the work below, rather than competing with an oversized company-name card.
- Keep the active view as the route H1; shared identity can be a prominent labelled non-heading block. Topic and section heading levels then remain predictable.

On mobile, company identity is 28px and long names wrap. Quote and watchlist action share a compact second row if they fit, then stack naturally. The view navigation remains reachable without shrinking its labels. Missing quote fields display their existing unavailable state, not a fabricated zero or a fresh-looking timestamp.

## 7. Company research summary — `/ticker/[symbol]`

### Current issue

Most sections share the same open white treatment and 24px heading/rule pattern. Topic summaries are small and spread across a very wide row. Per-topic evidence and model detail are hidden behind nested disclosures. Pending overview text removes the main focal paragraph and leaves the topic list to carry the page without a substantial reading region.

### Proposed composition

Use a broad primary reading region beside a clearly subordinate evidence/context area. Keep the existing six topics and the distinction between filing, publisher and public discussion material.

```text
shared company identity and local views
Research summary + short introduction

primary reading region                 evidence/context region
  latest substantive filing brief      original source descriptors
  or latest available topical analysis scope / available filing facts
  topical sections                     clearly labelled model detail

facts and interpretation
filing signal / activity themes
discussion coverage as compact secondary disclosure
```

### Detailed specification

- View title 32px; major section headings 28px; topic headings 18px; body 16px/1.60–1.65.
- The latest substantive brief is an editorial opening with a short attribution/source footer. Use 18px introductory text only where the paragraph genuinely introduces the research.
- If the latest filing brief is pending, show a compact original-material region and lead the main reading area with an available topical analysis. Label that analysis accurately; do not synthesise an unsupported new company overview.
- Topic summaries sit within a consistent reading surface. The selected/open topic has a clear internal boundary from its next neighbour.
- First available topic may open initially; available core prose should not require opening multiple additional disclosures.
- Original links for the open topic appear directly as evidence descriptors or in the corresponding evidence panel. Processing/model detail stays behind one secondary disclosure.
- When a topic changes, the evidence area's title identifies the topic whose sources are displayed. Filing sources must never appear as if they substantiate a separate discussion category.
- Limit prose to around 64–72ch while the complete composition remains wide. Give the right column actual sources and facts, rather than distributing confidence/source counts across blank space.
- Facts and interpretation receive two labelled groups when classification exists. Both use readable 16px content; distinguish their meaning through labels and subtle surface treatment rather than red/green judgement.
- Filing details and signal metadata are ledgers, not another row of oversized metric cards. Model confidence remains a classification measure.
- Themes remain filing-category descriptions. Public discussion collection state remains separate from public sentiment.

### Mobile and states

Bring relevant source descriptors directly after the analysis they support. Avoid stacking every desktop side panel ahead of the prose. Keep one concise processing notice per affected analysis rather than a series of equally large unavailable cards.

Test a complete overview, pending overview with available topics, all topics unavailable, missing classification, missing quote, missing citations, partial category/discussion errors, and a substantive long summary. Each should look intentionally structured. Independent requests retain independent retry/error handling.

## 8. Source records — `/ticker/[symbol]/news`

### Current issue

This view has a useful index/reader structure, but its regions need stronger surface and type distinction. On mobile, the complete index precedes the reader, so inspecting the selected document can involve substantial scrolling. The reader should feel like the principal document, not another list row.

### Proposed composition

Use approximately four columns for the source index and eight for the reader. A compact shared toolbar sits above the split. The index has a quiet neutral surface; the reader is white and spacious.

```text
Source records / count / collection scope
search + filters/order

neutral source index                   white selected reader
  kind/date                            full document title
  title/publisher                      publisher/date + original link
  selected indication                  substantive context
                                       changed/research angle if present
```

### Detailed specification

- View title 32px; selected title 28px/550; index title 16px/550; metadata 13px; reader prose 16px.
- Reader padding 32px desktop, 20px mobile. Keep a clear 24px gutter/boundary between the regions.
- Selected state combines neutral/brand wash with a persistent indicator and `aria-pressed`; colour alone is insufficient.
- Index rows receive 16–20px padding and predictable title/publisher grouping. Date should stay near its document rather than drifting to a separate small far-right column.
- Original action sits immediately below title/provenance, before lengthy analysis. It can be the principal button/link of the reader.
- Show only substantive Context, What changed and Research angle fields using existing text-quality helpers. Missing fields do not become three identical blank boxes.
- Use one compact incomplete-analysis notice when appropriate. Existing titles and original material remain the content in a pending case.
- Search uses a 48px field; filters/order remains a secondary accessible popover or disclosure. Search/count/filter reset belong to one tool region.

### Mobile interaction

Use a select/read drill-down within the same page. Initially display a compact selected-source summary and the reader. A “Change record” affordance opens the searchable index; selecting a document returns focus to its reader heading. Alternatively, a single inline reader can appear adjacent to the selected row. Choose one implementation and preserve a single authoritative reader in the DOM.

Do not leave a 70vh index as an unavoidable barrier before reading the first document. Retain the existing focus/jump semantics and clear selected-record announcement. Preserve filters and selection when returning to the index.

### States and scope

Cover loading, no records, no filtered matches, original URL missing, long title/domain, source request error and incomplete analysis. Keep “up to ten persisted records” scope explicit but quiet. Persistent record URLs/query selection are optional later work if stable identifiers support them; they are not a prerequisite for this visual migration.

## 9. Deep dive — `/ticker/[symbol]/deep-dive`

### Current issue

Chronology exists, but entries can still blend into a repeated sequence of grey date, title, body and source link. The word “Deep dive” also sits over a history that legitimately contains short pending records. The layout needs clear chapter boundaries without pretending every entry has completed analysis.

### Proposed composition

A restrained contents rail accompanies a generous chronological document. Dates define chapters. Substantive entries carry the reading weight; pending entries remain compact and useful.

```text
Deep dive / accurate collected-history explanation

contents rail                         dated reading document
  date + short title                  date + source kind
  active entry                        complete title
                                      analysis paragraphs
                                      original source descriptor
                                     ─────────────────────────
                                      next dated entry
```

### Detailed specification

- Contents column about 240–280px; document gets the remaining useful width. Main prose around 64–72ch.
- View title 32px; entry titles 28px desktop/22px mobile; dates/kinds 13px; prose 16px/1.65.
- Entry-to-entry gap 40–48px, with a quiet rule or chapter boundary. Within an entry, title/prose spacing is 12–16px.
- The date and source type remain attached to the entry. Avoid repeating an identical date again under its original link when it provides no additional context.
- Preserve paragraph breaks from the stored detail. Do not paraphrase or generate additional research to fill the page.
- Pending entries show title, actual date, a short pending label and the original source. They should not occupy the same minimum height as a substantive essay.
- Contents titles may be compact, but the article title remains complete. Anchor targets account for the sticky header.
- A sticky contents rail must be bounded by the history region and work on short desktop heights. Prefer page scrolling to multiple unnecessary nested scroll containers.

### Mobile and states

Collapsed contents comes before the first entry with a count and clear expansion action. Source descriptors follow each entry directly. The first useful entry should not be displaced by an expanded ten-item contents list.

Cover all pending, mixed substantive/pending, no history, network error, long article and missing date. Preserve the existing ten-entry/newest-first service scope and avoid implying an exhaustive historical archive.

## 10. Watchlist — `/watchlist`

### Current issue

The existing grid has the beginnings of a useful composition, but small summary text, repeated badges and an add-company tile can make it look like generic dashboard cards. The signed-out/loading state also needs a clear place in the same design language.

### Proposed composition

Use a 44px page title, a restrained saved-company count and one clear Add company action. Render three substantial company modules on a wide screen, two where appropriate and one on mobile. The grid should reflect real saved companies; it should not be padded with artificial empty slots.

### Detailed specification

- Header description 18px; count 14px. Remove redundant “Saved companies” headings where the title and count already explain the collection.
- Company modules: 20px company name; 13px ticker/exchange/date; substantive brief 15–16px; clearly labelled available classification/status.
- Use consistent internal groups with 12px identity/description spacing and 20–24px before the footer action/date.
- Keep quote/classification data only when supplied by the existing watchlist model. Do not add return charts, portfolio weights or performance metrics that do not exist.
- Use one shared grid surface/geometry with a clear distinction between company identity, current context and last brief date. Equal row heights can be achieved through layout; no filler text is needed.
- Remove action receives an accessible name and a full hit area, positioned so it cannot be mistaken for the company link.
- Add company belongs in the header as the main action. A secondary grid-end invitation may exist, but it should not impersonate a saved company or dominate a small watchlist.

### Add-company dialog

Keep existing search, duplicate prevention, adding state, failure feedback, focus trap, Escape and focus return. Use 28px title, 16px explanation, 48px field and comfortable result rows. On mobile the dialog becomes a roomy contained sheet; its searchable results remain scrollable without hiding the submit/add feedback.

### States

Signed out: one deliberate sign-in panel with the existing route, rather than a disabled work area that implies an empty watchlist. Empty authenticated collection: concise explanation and Add company. Loading: stable grid/row geometry. Failure: retry within the collection region. Failed removal must restore the true collection. Visual migration must not create, remove or modify saved companies as a styling side effect.

## 11. Alert settings — `/settings/notifications`

### Current issue

This route already has a useful rules/status split, but its independent scale and legacy/replacement rules make it feel separate from the rest of the app. Blue 11px labels and an oversized heading are not needed to establish hierarchy.

### Proposed composition

Use a 34px task title, 18px explanation, a primary rules form and a quieter delivery-status panel. Make the task sequence explicit: enable alerts → choose classification confidence → select sentiments → save.

### Detailed specification

- Main form has three separated groups with 24–32px internal section gaps. Minor headings are 18–20px; legend/field labels 14–16px.
- Enable switch is paired with its explanation. Its hit area remains sufficient even if its visible track is compact.
- Confidence percentage uses tabular numerals and a clear label. Explain the classification meaning without promising stronger investment outcomes.
- Sentiment selections use labelled checkboxes and semantic markers. Do not make every selected option a bright brand pill.
- Save preferences is the one primary action, with explicit dirty/disabled/saving/saved feedback.
- Delivery panel uses a 20px title/identity role where suitable, 14px explanatory copy and 13px ledger labels. Email addresses wrap rather than overflow.
- Verified/pending/failed state is distinct from delivery success/failure. Feature-unavailable state cannot look like an enabled alert subscription.
- Resend verification remains a secondary action with the existing cooldown/429 and requesting states.

### Mobile and states

Show a compact verification/delivery summary before the rules when it affects whether alerts can arrive. Put verbose delivery details after the form. Do not create a long status card that pushes all controls below the first screen.

Validate unverified, pending, verified, failed, last-delivery failure, feature disabled with alerts on/off, saving, saved, dirty and auth redirect. Preserve current backend feature gating and existing preferences semantics.

## 12. About — `/about`

### Current issue

The route is a short, narrow information page with two ruled sections. It accurately explains the product, but has little compositional distinction from Terms or Data sources.

### Proposed composition

Use a public introduction beside a truthful workflow exhibit. Follow with the existing preparation explanation and product-boundary information as two distinct chapters. The source-directory action closes the page naturally.

### Detailed specification

- Title 52px desktop/34px mobile, introduction 18px with a controlled width.
- The exhibit uses three actual stages from the existing description: collection, AI-assisted preparation and original-source verification. It can be a structured diagram or content modules, not a decorative illustration of imaginary capabilities.
- Preparation chapter gets a 28px heading and 16–18px readable copy. Product-boundary material can use a quieter neutral region with the same readable body size.
- Use 64–80px between chapters; no need to fabricate a long page with invented team history, customers, testimonials or statistics.
- Keep the existing Data sources destination as the principal next step.

On mobile, the explanation precedes the diagram when that better serves comprehension. The page remains a concise public introduction, not a dashboard and not a restatement of the entire home page.

## 13. Data sources — `/data-sources`

### Current issue

All four source families are presented as similar heading/paragraph blocks. The distinction between official filings, publisher news, public discussion and market quotes would benefit from a stronger directory structure.

### Proposed composition

A 52px public title and 18px introduction lead into a broad source directory. Each row has a stable source-family identity region and a more generous description/limitations region.

### Detailed specification

- Four source rows retain their existing factual descriptions.
- Source-family heading 20–22px; explanation 16px/1.60; compact limitation/provenance information 14px where already supported.
- Use 24–32px row padding and a 24–32px column gap. A quiet rule separates families; a neutral surface can contain the whole directory.
- Official material, publisher material, discussion and quotes receive readable text labels. An icon is an optional aid, not the sole distinction.
- Preserve the notice about opening the original and missing stored URLs, but give it a deliberate compact notice region below the directory.
- Do not invent publisher partnerships, licensing assurances, guaranteed freshness or coverage counts. Quote delay/unavailability remains explicit.

Mobile rows stack identity above explanation. Keep source-family groups clearly separated while avoiding a new rounded card around every sentence. This route should explain the evidence model that users encounter in the research views.

## 14. Terms — `/terms`

### Current issue

The existing page is legible, but uses the same presentation as general information pages. It needs a deliberate document layout rather than increased width for its own sake.

### Proposed composition

Use a centred document assembly around 1024px within the shared shell. A narrow contents column accompanies a 680–752px reading region when there is room. With the current short document, contents may remain a simple compact list rather than a heavy sticky panel.

### Detailed specification

- Title 44–52px desktop/32–34px mobile, depending on document frame fit.
- Existing section headings 22–24px, body 16px/1.65 and 32–40px chapter gaps.
- Preserve existing legal wording exactly during a visual migration. Do not insert a new effective date or terms version without a real supplied value.
- Contents links match actual section headings and use meaningful anchor targets. Make the relevant section visible below the sticky header.
- Use comfortable paragraph widths and quiet rules only where they reinforce chapters. Avoid alert-coloured boxes or promotional CTA styling around legal paragraphs.
- The document can remain narrower than the research feed. That is purposeful reading geometry, not failure to use horizontal space.

Mobile contents becomes a compact disclosure or short list. Full text remains visible and readable at 200% zoom.

## 15. Account form family

All account pages use the same field, feedback and panel vocabulary. Their security logic remains in the existing auth modules. Quartr's public typography/composition is the visual reference; this plan does not require visiting or reproducing its login flows.

### Shared specification

- Title 34px desktop/28px mobile, description 16px/1.50.
- Form content width 420–460px; panel padding 32px desktop/20–24px mobile.
- Labels 14px/500; inputs 16px and 48px high; field-to-field gap 20–24px.
- Primary submission full-width where appropriate, at least 48px high. Secondary navigation is a clearly grouped line below feedback.
- Use left-aligned reading/field content. Do not centre every helper message or spread account links into disconnected blocks.
- Keep validation, busy and server errors visible in the same form region. Retain autocomplete, required, maxlength, minimum length and password visibility semantics.
- Support mobile keyboards, short screens, password managers and text zoom. The form must scroll rather than be vertically clipped.

### Sign in — `/sign-in`

Use the existing welcome description beside the form on a roomy desktop if it adds useful context; otherwise centre the form. Keep email/password as the initial task. The MFA challenge replaces the field group while retaining the page frame and clear progress/context.

The primary label changes with the existing state: sign in, confirm code or checking. Preserve Cognito-dependent forgot-password visibility and the current next/redirect handling. Inline setup secrets, when the existing flow provides them, require a controlled readable region rather than spilling into a general paragraph.

States: invalid credentials, auth disabled/configuration failure, submitting, MFA challenge, MFA setup continuation, confirmation redirect and reset redirect. Styling must not weaken or bypass any challenge.

### Sign up — `/sign-up`

Use a restrained introduction + form split on desktop. The current name/email/password sequence remains the central region, with a concise security note attached to the password group or form footer.

Do not add testimonial panels, unsupported watchlist benefits or social-sign-in buttons that do not exist. Preserve the current deployment-specific password requirement and confirmation step. On mobile, avoid oversized headings and a disconnected security note far below the action.

States: validation, submitting, existing account, service failure and confirm-account transition. The visual plan does not add a new terms-acceptance mechanism or change account creation rules.

### Forgot password — `/forgot-password`

Use a compact one-field form, not a marketing split. Maintain the existing non-enumerating account-existence wording. Description sits close to the title, email label sits above its field, and Send reset code is the one primary action. Back-to-sign-in is secondary.

States: empty/invalid email, sending, network/provider failure and transition to reset. Do not expose whether a particular address has an account through a new design message.

### Reset password — `/reset-password`

Keep email, reset code and new password in a compact contained sequence. Password requirements sit near the password field. The code input can use tabular numerals but should remain a single accessible input unless a multi-cell component genuinely improves the flow.

Retain existing session-provided email behaviour, resend handling and account-provider requirements. Do not add an automatic credential submission, password change or success message before the existing auth operation succeeds.

States: invalid/expired code, password validation, submitting, resend and successful return to sign in.

### Confirm signup — `/confirm-sign-up`

Use the same code-form structure as reset, with the existing email and confirmation-code fields. Group resend timing/action with its explanation. The primary confirmation action and the secondary “already confirmed” navigation must not compete visually.

States: missing email, invalid/expired code, confirming, resending, cooldown and successful sign-in navigation. Keep pasted codes and one-time-code autocomplete usable.

### Authenticator setup — `/mfa-setup`

Use a step-oriented task panel: start → provision key/open authenticator → enter code → confirmed. Step labels are ordinary readable text, not a large decorative progress graphic.

The current implementation supplies a shared key and authenticator URI; it does not render a QR code. Style those existing capabilities clearly. A QR component would be separate capability work, not a decorative placeholder. The actual key needs a bounded monospace region that wraps safely on mobile and remains easy for the user to use.

Keep the administrator requirement and provider-disabled branch intact. Success links back to the existing watchlist route. Do not begin setup as a side effect of previewing its design.

### Sign out — `/sign-out`

The current route performs sign-out and returns home; it renders no content. Keep that automatic task flow. If the transition is long enough to warrant feedback, display a minimal “Signing out” status in the shared shell. Do not introduce a large landing screen, another confirmation step or a fabricated success before the operation completes.

## 16. Transactional result family

Verification, unsubscribe and recovery pages should be calm and decisive. They do not need to fill a desktop horizontally. Their primary content is an outcome, its short explanation and one useful next action.

### Shared specification

- Controlled result width 480–560px; title 34px desktop/28px mobile.
- Content generally left aligned, with a small optional status icon and 16px explanatory paragraph.
- Use 12px title/body spacing and 24px before the action. Avoid a huge mail icon, a decorative blue eyebrow and a large repeated heading all competing for the same attention.
- Use semantic status where it helps, but an incomplete or missing link is not necessarily an alarming red full-page failure.
- Processing feedback uses an accessible live status and reserves stable geometry. Each result has exactly one principal recovery/next action with optional secondary navigation.

### Verify notification email — `/verify-notifications`

Represent working, complete, missing/invalid and error as four clear result states. Confirmation is shown only after the existing token verification succeeds. Keep the existing Open alert settings destination and retry behaviour. Do not expose or copy the token into the visual content.

The route performs verification automatically when a token is supplied. Visual previews should use missing-token rendering or controlled fixtures, rather than consuming real email links casually.

### Unsubscribe — `/unsubscribe`

Preserve working, complete, missing and error states. The completion wording currently avoids revealing whether a token matched a subscription; retain that property. Keep Return home or Open alert settings as appropriate to the actual branch.

The missing-token capture demonstrates an oversized icon/eyebrow/title stack and generous unused padding. Reduce those competing elements into one deliberate result panel. Do not make a completed unsubscribe look like a promotional re-subscription page.

### Not-found boundary

Use a 34px recovery title, 16px explanation and the current Return home/Search companies destinations. Search can be the visually emphasised recovery action where the address appears to be an unsupported company, but do not guess an alternative company from a malformed symbol.

Keep the actual error status/metadata and supported-route behaviour. A beautiful recovery page is not a substitute for fixing links that should never point at unsupported ticker routes.

## 17. Cross-page state design

| State | Visual treatment | Behaviour requirement |
|---|---|---|
| Initial loading | Geometry appropriate to the future region | Label the region and preserve useful known content where possible |
| Background refresh | Quiet attached progress | Do not blank a readable current document unnecessarily |
| Empty collection | Short explanation and useful next action | Distinguish no data from a failed request |
| Filtered empty result | Filter-specific message + clear reset | Keep scope and filters visible |
| Pending analysis | Compact title/provenance/original region | Never invent a paragraph to fill the layout |
| Partially available research | Available material remains primary | Error/retry only affects its actual resource |
| Missing source URL | Explicit unavailable provenance state | No fake or unsafe original link |
| Unavailable quote/metric | Quiet correctly labelled value | Do not display zero or imply live freshness |
| Auth required | Contained access explanation/action | Preserve the intended destination through sign-in |
| Saving/adding | Attached busy state | Avoid duplicate submissions and preserve the user's draft |
| Failed save/add/remove | Relevant error and recovery | Keep or restore the true data state |
| Completed task | Clear outcome + next destination | Do not announce success before the operation succeeds |

State styling is part of the design, not the final fallback appended after a polished happy-path mockup.

## 18. Page acceptance matrix

| Family | What a completed redesign must demonstrate |
|---|---|
| Home/About | Strong introduction and purposeful companion exhibit without photography or invented proof |
| Search | Stable identity/data columns, readable mobile count and useful results visible quickly |
| Announcements | Clear date/record grouping, original actions, useful context and preserved filters/pagination |
| Company identity | Balanced identity/quote/action and recognisable local navigation across three views |
| Summary | Substantial readable analysis, directly related evidence and deliberate sparse-data composition |
| Sources | Selected document clearly dominant; readable complete title; mobile reader easily reached |
| History | Clear chronological chapters, bounded contents and honest pending entries |
| Watchlist | Consistent real company modules and clean signed-out/empty/add/remove states |
| Alerts | Clear task sequence, readable confidence meaning and correct verification/delivery states |
| Sources/Terms | Distinct directory/document structures with preserved factual/legal content |
| Account forms | One field/feedback system, readable mobile fields and unchanged security flow |
| Result pages | Clear outcome/action, restrained iconography and no account/token disclosure |

## 19. How to compare the redesign with the reference

Compare each archetype to the relevant public reference structure: broad grouped panels for home/watchlist; a dense aligned ledger for search/facts; a deliberate feature/reading section for company analysis; controlled introduction/action grouping for forms and results. Do not compare a sparse unclassified filing to a marketing page's photographic hero and solve the difference by adding empty boxes.

For each screen, capture the same viewport and a stated content state. Check the shared plan's typography, separation, horizontal purpose, composition, surface, detail, state resilience and consistency dimensions. Record concrete defects such as a cramped date, an unrelated evidence rail, a competing second title or a row whose metadata is no longer attached to its document.

The intended result is a consistent premium quality across the entire app, with each page arranged around its actual task. The reference stays stable; individual pages should not drift into unrelated dashboard, terminal or landing-page styles during implementation.

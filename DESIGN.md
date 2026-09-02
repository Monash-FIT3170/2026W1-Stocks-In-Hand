# StonksInHand design system

## Product direction

StonksInHand is a source-first ASX research product. The interface should feel calm, exact, trustworthy, and materially easier to scan than a traditional financial terminal. Quartr is the dominant design reference for composition, restraint, navigation, typography, and motion. The result must remain recognisably StonksInHand and must not copy Quartr trademarks, text, imagery, or proprietary assets.

Mode: **Operate**. Marketing moments may persuade, but company research, announcements, watchlists, authentication, and settings must remain task-oriented.

Design dials:

- Variance: 6/10
- Motion: 6/10
- Density: 6/10

## Visual atmosphere

- Near-white cool canvas with white and pale-blue surface steps.
- Near-black navy ink rather than green typography.
- Cobalt blue is the only brand/action colour.
- Positive green, warning amber, and negative red are semantic only.
- Hairline borders and surface contrast carry hierarchy; shadows are rare and quiet.
- Corners are controlled: 8px controls, 12px cards, 16px feature panels. Pills are reserved for compact statuses and filters.
- Product data and source provenance are the visual protagonists. Do not add decorative stock photography.

## Colour tokens

```css
--canvas: #fbfcfc;
--canvas-subtle: #f4f6f8;
--surface: #ffffff;
--surface-raised: #f8fafc;
--surface-tint: #edf2ff;
--ink: #101214;
--ink-secondary: #4e5965;
--ink-tertiary: #707b87;
--line: #dfe4e8;
--line-strong: #c8d0d7;
--brand: #2f5bea;
--brand-hover: #2448c7;
--brand-soft: #e9eeff;
--positive: #13795b;
--positive-soft: #e5f5ef;
--warning: #9a6700;
--warning-soft: #fff3d6;
--negative: #b4233b;
--negative-soft: #fdecef;
--focus: #315fea;
--overlay: rgba(16, 18, 20, 0.48);
```

All text/background pairs must meet WCAG AA. Never use colour alone to communicate sentiment or state.

## Typography

- Primary family: Inter Variable where available; fallback `Inter, "Helvetica Neue", Arial, sans-serif`.
- Numeric and ticker accents: `ui-monospace, "SFMono-Regular", Consolas, monospace`.
- Display weight: 550–600, not extra-black.
- Body weight: 400–450.
- Strong negative tracking is reserved for large headings.

Scale:

- Display: clamp(48px, 7vw, 76px), 0.95 line-height, -0.05em tracking.
- Page title: clamp(40px, 5vw, 60px), 1.0 line-height, -0.045em tracking.
- Section title: clamp(28px, 3vw, 38px), 1.1 line-height, -0.035em tracking.
- Card title: 20–24px, 1.25 line-height, -0.02em tracking.
- Body large: 18px / 1.55.
- Body: 16px / 1.55.
- Body small: 14px / 1.45.
- Caption: 12px / 1.4, only for tertiary metadata.

## Layout and rhythm

- Shared maximum content width: 1240px.
- Desktop gutter: 32px; tablet: 24px; mobile: 16px.
- Section spacing: 96px desktop, 72px tablet, 56px mobile.
- 4px base spacing scale: 4, 8, 12, 16, 24, 32, 48, 64, 96.
- Prefer open sections and dividers over wrapping every group in a card.
- Data-heavy ticker pages may use a 12-column grid with a 4-column aside.
- Mobile must preserve complete DOM reading order and avoid mandatory horizontal scrolling except for explicitly scrollable tab lists.

## Navigation

- Desktop header is 64px and sticky. After the first 56px of page scroll it compresses into a centred floating navigation surface with a 14px radius; the transformation must preserve reading position.
- Brand sits left, primary destinations in the centre, account action right. The compact state may hide the brand wordmark but must keep the recognisable mark and accessible name.
- `Product +` groups company search, market updates, watchlist, and alerts. `About +` groups the platform overview, data sources, and terms. Each opens a bordered mega-menu with a title and one-line description per destination.
- The plus rotates to a minus/cross state. Menu enters with opacity, 8px vertical translation, and subtle scale.
- Escape closes the menu. Focus returns to the trigger. Clicking outside closes it.
- Mobile uses a real menu panel rather than horizontally scrolling desktop links.

## Components

### Buttons

- Primary: ink background, white text, 8px radius, 44–48px high.
- Brand: cobalt background for the single highest-priority action on a surface.
- Secondary: white/transparent surface, hairline border.
- Tertiary: text with right-arrow movement on hover.
- Press state: translateY(1px) and slight scale reduction; never bounce.

### Cards

- Default: white surface, 1px line, 12px radius, no shadow.
- Hoverable: line strengthens, content or arrow translates 2–4px; no dramatic lift.
- Feature panel: 16px radius with a distinctive background tint or dark inverse surface.
- Avoid nested cards and generic side-tab accents.

### Inputs

- Visible label, 48px minimum height, 8px radius, white surface, hairline border.
- Focus uses a two-stage cobalt ring; errors appear directly below the field.
- Search always has an explicit submit action and clear state when populated.

### Status and sentiment

- Sentiment uses semantic colour plus icon/label.
- Status pills are compact and never used as generic decoration.
- Ticker symbols use mono type and restrained neutral containers.

### Source provenance

- Citations and source links are a signature component, not footnote debris.
- Use a numbered source rail or compact source list with publisher, date, and external-link affordance.
- Source-aware claims should visually connect to their supporting records where the data permits.

## Motion system

Motion should communicate hierarchy and continuity, not decorate empty space.

- Signature easing: `cubic-bezier(0.22, 1, 0.36, 1)`.
- Utility easing: `cubic-bezier(0.4, 0, 0.2, 1)`.
- Micro-interactions: 150–220ms.
- Menus/drawers: 280–350ms.
- Section entrances: 450–650ms with 40–70ms stagger.
- Page content enters through masked/translated typography and restrained opacity.
- Cards may reveal in a staggered sequence when entering the viewport.
- Images or large decorative product panels may scale from 1.02 to 1.0.
- Never animate layout dimensions when transform/opacity can express the same transition.
- No scroll-jacking. Pinned storytelling is allowed only on future marketing surfaces where the non-animated reading order remains complete.
- Under `prefers-reduced-motion: reduce`, render final states immediately and retain only essential state feedback.

## Responsive behaviour

- Breakpoints: 640px, 768px, 1024px, 1280px.
- Navigation changes to a mobile menu below 768px.
- Multi-column research layouts collapse to one column below 980px.
- Touch targets are at least 44px with 8px between adjacent targets.
- Test at 375px, 768px, 1024px, and 1440px, plus 200% text zoom.

## Content preservation

- Existing factual copy, labels, API data, route behaviour, authentication logic, and error states stay unless a wording change is required for clarity.
- Existing visual imagery and decorative treatments do not need to be preserved.
- Do not invent financial metrics, claims, testimonials, customers, or performance data.

## Explicit anti-patterns

- No mint-heavy or eco-fintech palette.
- No green headings or green primary buttons.
- No oversized pill controls everywhere.
- No glassmorphism, neon terminal aesthetic, or generic AI gradients.
- No card grids where spacing and dividers would communicate the hierarchy better.
- No tiny uppercase labels below 12px.
- No animation without a reduced-motion path.
- No copied Quartr brand assets, wording, or proprietary imagery.

# ProctorAI Design Tokens

> Written before any component code. This file is the single source of truth for the visual system.

---

## Design Principles (ProctorAI-specific)

### 1. Evidentiary weight
Every datum shown is potentially part of a formal academic proceeding. Typography, spacing, and hierarchy make data unambiguous. No decorative clutter competes with evidence. Tables are first-class citizens.

### 2. Graduated tension
The interface modulates intensity by context. A dashboard is calm. The Live Monitor runs warm with latent alertness. An active alert is unmistakable but controlled. A penalty confirmation is grave. The UI temperature tracks the stakes.

### 3. Institutional authority
This is a university's academic integrity process. It feels procedural, credible, and formal — like a case-management system for an academic tribunal. Not friendly, not rounded, not startup.

### 4. Restraint as design
One bold element per screen maximum. Everything else is quiet infrastructure that recedes so the focal point commands attention.

---

## Color Tokens

### Core Palette

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg-primary` | `#F4F5F7` | `#111318` | Page background — cool grey, not warm |
| `--bg-surface` | `#FFFFFF` | `#1A1D24` | Cards, panels |
| `--bg-surface-raised` | `#F0F1F4` | `#22262E` | Nested surfaces, table headers |
| `--bg-surface-overlay` | `#FFFFFF` | `#252830` | Modals, dropdowns |
| `--text-primary` | `#171A1F` | `#E8EAED` | Primary content |
| `--text-secondary` | `#5F6368` | `#9AA0A6` | Supporting text |
| `--text-muted` | `#80868B` | `#6B7280` | Disabled, placeholders |
| `--accent-primary` | `#2B5EA7` | `#6FA3EF` | Primary actions, active nav |
| `--accent-primary-hover` | `#1E4A8A` | `#8BB8F4` | Hover state |
| `--accent-primary-subtle` | `#E8EFF8` | `#1C2A40` | Selected row bg, active indicator bg |
| `--border-default` | `#DADCE0` | `#2D3139` | Dividers, card edges |
| `--border-strong` | `#BDC1C6` | `#3C4149` | Emphasized borders |
| `--border-focus` | `#2B5EA7` | `#6FA3EF` | Keyboard focus ring |

### Behavior Type Colors

Each behavior has a distinct hue family, verified against deuteranopia/protanopia simulation. Every usage pairs color with an icon — never color alone.

| Behavior | Light | Dark | Icon | Shape |
|---|---|---|---|---|
| Gaze Deviation | `#7B61FF` | `#A78BFA` | Eye/iris | Circle |
| Head Pose Violation | `#0891B2` | `#22D3EE` | Rotation arrows | Diamond |
| Lip Movement | `#D97706` | `#FBBF24` | Sound wave | Triangle |
| Phone Detected | `#DC2626` | `#F87171` | Phone outline | Square |
| Unauthorised Object | `#C2410C` | `#FB923C` | Shield-alert | Hexagon |

### Case Status Colors

| Status | Light | Dark | Shape |
|---|---|---|---|
| Pending Review | `#D97706` | `#FBBF24` | Half-filled circle |
| Confirmed | `#DC2626` | `#F87171` | Filled circle |
| Dismissed | `#5F6368` | `#9AA0A6` | Strikethrough circle |
| Escalated | `#7C3AED` | `#A78BFA` | Arrow-up circle |

### Functional Colors

| Token | Light | Dark | Usage |
|---|---|---|---|
| `--color-success` | `#16A34A` | `#4ADE80` | Positive confirmations |
| `--color-warning` | `#D97706` | `#FBBF24` | Warnings, pending states |
| `--color-error` | `#DC2626` | `#F87171` | Errors, destructive actions |
| `--color-info` | `#2B5EA7` | `#6FA3EF` | Informational |

---

## Typography

| Role | Font | Weights | Usage |
|---|---|---|---|
| Headings / Display | **Sora** | 600, 700 | Page titles, section headers, stat values. Geometric sans with wider apertures — gives headings technical character without being decorative. |
| Body / UI / Data | **Inter** | 400, 500, 600 | Body text, table content, form labels, buttons, navigation. Designed for screens with excellent tabular-number support. |

### Scale

| Name | Font | Size | Weight | Line Height | Usage |
|---|---|---|---|---|---|
| `display-lg` | Sora | 30px | 700 | 1.2 | Page titles |
| `display-md` | Sora | 24px | 600 | 1.25 | Section headers |
| `display-sm` | Sora | 20px | 600 | 1.3 | Card titles |
| `heading` | Sora | 16px | 600 | 1.4 | Table column headers, sidebar sections |
| `body-lg` | Inter | 16px | 400 | 1.5 | Primary body text |
| `body` | Inter | 14px | 400 | 1.5 | Default body text |
| `body-sm` | Inter | 13px | 400 | 1.45 | Secondary text, timestamps |
| `label` | Inter | 12px | 500 | 1.4 | Form labels, chip text, table secondary |
| `stat` | Sora | 32px | 700 | 1.1 | Dashboard KPI values |

---

## Spacing

Base unit: 4px. Scale: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.

- Content padding (cards): 16px–20px
- Section gaps: 24px
- Page margin: 24px–32px
- Table cell padding: 12px horizontal, 10px vertical

---

## Border Radius

Not uniform — hierarchy through shape:

| Element | Radius |
|---|---|
| Inline badges/chips | 2px |
| Data containers, table cells | 4px |
| Interactive elements (buttons, inputs, cards) | 6px |
| Modals, large panels | 8px |
| Avatars | 50% (circle) |

---

## Elevation / Shadow

Minimal — elevation through border + background, not shadow:

| Level | Light | Dark |
|---|---|---|
| Surface | `0 1px 2px rgba(0,0,0,0.05)` | `0 1px 2px rgba(0,0,0,0.3)` |
| Raised | `0 2px 8px rgba(0,0,0,0.08)` | `0 2px 8px rgba(0,0,0,0.4)` |
| Overlay (modal) | `0 8px 24px rgba(0,0,0,0.15)` | `0 8px 24px rgba(0,0,0,0.5)` |

---

## Layout

- **Sidebar**: 240px expanded, 64px collapsed (icon-only). Fixed position.
- **Header**: 56px height. Sticky top.
- **Content area**: Single-column primary. Max-width 1280px for wide screens. Tables stretch full width.
- **Breakpoints**: 640px (mobile), 768px (tablet), 1024px (desktop), 1280px (wide)

---

## Anti-slop Audit (what was deliberately chosen against defaults)

| Default I rejected | What I used instead | Why |
|---|---|---|
| Warm cream `#FDF8F5` / terracotta accent | Cool grey `#F4F5F7` / steel blue `#2B5EA7` | Institutional, not cozy. This is a monitoring system, not a wellness app. |
| Uniform 12px border-radius everywhere | 2px/4px/6px/8px graduated scale | Hierarchy through shape. Badges are tight, modals are slightly softer, but nothing is "bubbly." |
| Identical card grid layout | Table-first layout with selective cards for KPIs only | This is a case management and monitoring tool. Data density matters more than visual symmetry. |
| Subtle pastel semantics (all similar saturation) | Five distinct hue families spanning purple→teal→amber→red→orange | Must be distinguishable for colorblind users. Each backed by a unique icon shape. |
| Box-shadow-heavy elevation | Border + background differentiation, minimal shadow | Cleaner, more institutional. Shadow is reserved for true overlays (modals, dropdowns). |
| Rounded-pill buttons / links | 6px radius, no arrows, plain active-voice labels | "Confirm case" not "Submit →". Professional, not playful. |
| ALL-CAPS eyebrow labels | Sentence-case section headings in Sora 600 | ALL-CAPS reads as shouting in an academic integrity context. Sora at weight 600 is authoritative without yelling. |
| Middle-dot meta strings | Structured layout: separate labeled fields or slash-separated | "Room 4, CS-301, 09:14" or individual labeled fields, not "Room 4 · CS-301 · 09:14". |

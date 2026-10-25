# Earn & Pay — Design System & UI/UX Specification

**Design Direction:** Editorial Local-Work Marketplace  
**Core Attributes:** Human, Clear, Trustworthy, Dignified, Accessible, Purpose-Built

---

## 1. Visual Philosophy

Earn & Pay rejects generic AI-generated SaaS templates (dark neon gradients, glassmorphism, floating decorative blobs, and repetitive 3-card grids). Instead, it takes inspiration from civic service design and classic editorial print layouts:
- **Warm Ivory (`#F7F4EC`)** paper-like canvas that reduces glare on outdoor mobile screens.
- **Deep Navy (`#17253D`)** ink-like typography for authority and maximum legibility.
- **Vibrant Orange (`#F07845`)** tactile action triggers and key wage/opportunity highlights.
- **Soft Sage (`#DCE7D8`)** calm, supportive panels for safety notices, match reasons, and verified badges.

---

## 2. Color Tokens & Contrast Compliance

| Token Name | CSS Variable | Hex Value | Usage & Accessibility Notes |
| :--- | :--- | :--- | :--- |
| **Warm Ivory** | `--color-bg-canvas` | `#F7F4EC` | Main page background across public and workspace views |
| **Pure White** | `--color-bg-surface` | `#FFFFFF` | Form containers, job ledger rows, elevated detail panels |
| **Soft Sage** | `--color-bg-sage` | `#DCE7D8` | Secondary panels, safety callouts, supportive tags |
| **Deep Navy** | `--color-text-primary` | `#17253D` | Primary text, headings, primary navigation (`14.2:1` on Ivory, AAA) |
| **Muted Gray** | `--color-text-secondary` | `#59606D` / `#707783` | Captions, metadata, timestamps (`#59606D` used for small text to guarantee `> 4.5:1` AA contrast on Ivory) |
| **Vibrant Orange** | `--color-accent-primary` | `#F07845` | Primary CTA buttons (paired with `#17253D` Deep Navy bold label or darkened `#C85322` for white text contrast) |
| **Status: Verified / Accepted** | `--color-status-success` | `#1E6B43` | Accepted applications, verified badges (always paired with icon + text label) |
| **Status: Pending / Review** | `--color-status-warning` | `#9A5B13` | Pending review, expiring deadlines (paired with clock icon + text label) |
| **Status: Danger / Rejected** | `--color-status-danger` | `#B42318` | Form validation errors, rejected status, scam warnings |

> **Accessibility Rule:** Never rely on color alone to convey application status, verification level, or form errors. Every status badge includes a distinct text label and semantic symbol.

---

## 3. Typography & Type Scale

- **Display & Editorial Headings (`--font-display`):** `'Fraunces'`, `'Georgia'`, `'Times New Roman'`, serif — warm, authoritative editorial character for hero and page titles.
- **Interface, Forms & Data (`--font-sans`):** `'Plus Jakarta Sans'`, `'Inter'`, system-ui, -apple-system, sans-serif — high x-height, clear numerals for wages, pincodes, and schedules.
- **Monospace Metadata (`--font-mono`):** `'JetBrains Mono'`, monospace — used for pincodes, reference IDs, and explicit wage figures.

| Level | CSS Variable | Size (Fluid / Rem) | Line Height | Weight | Use Case |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Display Hero** | `--text-display` | `clamp(2.25rem, 4vw + 1rem, 3.5rem)` | `1.1` | `700` | Landing page hero ("Find Work. Earn Money. Build Your Future.") |
| **Page Title (H1)** | `--text-h1` | `clamp(1.75rem, 2.5vw + 1rem, 2.5rem)` | `1.18` | `700` | Primary page heading |
| **Section Title (H2)** | `--text-h2` | `clamp(1.375rem, 1.5vw + 0.8rem, 1.875rem)` | `1.25` | `600` | Major section headers |
| **Subheading / Job Title (H3)** | `--text-h3` | `1.25rem` (`20px`) | `1.35` | `600` | Job listing titles, panel headers |
| **Body Large** | `--text-body-lg` | `1.125rem` (`18px`) | `1.6` | `400` | Lead paragraphs, job descriptions |
| **Body Base** | `--text-body` | `1rem` (`16px`) | `1.55` | `400` | Standard interface copy and form inputs (prevents iOS zoom) |
| **Label / Metadata** | `--text-sm` | `0.875rem` (`14px`) | `1.4` | `500` | Form labels, table headers, badges, timestamps |

---

## 4. Distinct Page Compositions (Anti-Template Architecture)

1. **Landing Page (Editorial Broadsheet Composition):**
   - Asymmetric split masthead with bold serif statement, dual role entry path ("Looking for Local Work" vs. "Hiring Reliable Staff"), inline pincode/category search bar, live job ticker ledger pulled from PostgreSQL, two-column Worker vs. Employer breakdown, and prominent Trust & Safety charter.
2. **Job Discovery Page (Split Filter-and-Ledger Layout):**
   - Sticky filter rail on desktop (collapsible drawer on mobile) paired with high-density structured job rows displaying upfront wage (`₹800 / day`), shift hours, locality + pincode, vacancies, and deadline.
3. **Job Details Page (Structured Fact-Sheet Specification):**
   - Top compensation banner, structured key-value grid for hours/vacancies/location/deadline, full responsibilities, employer profile sidebar, safety checklist box, and sticky mobile Apply bar.
4. **Worker Workspace (Personal Action & Timeline View):**
   - Compact navigation rail, profile completion meter, chronological application status tracker with clear visual steps, and explainable rule-based job matches.
5. **Employer Operations Workspace (Hiring Ledger View):**
   - Operational summary strip (Active Jobs, Total Applicants, Pending Review), structured vacancy management table, and candidate evaluation drawers with confirmation modals for hiring actions.

---

## 5. Accessibility & Interaction Standards

- **Touch Targets:** Minimum `44px × 44px` hit area on all interactive buttons, links, checkboxes, and filter controls.
- **Keyboard Focus:** High-visibility `3px solid #F07845` focus ring with `2px` offset (`:focus-visible`).
- **Reduced Motion:** Respects `@media (prefers-reduced-motion: reduce)` by disabling smooth scrolling and transitions.
- **Form Usability:** Explicit `<label for="...">` on every input, helpful hint text (`aria-describedby`), and inline server/client validation summaries.

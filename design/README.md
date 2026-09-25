# BucketIO Directory: website handoff

A standalone marketing site for **BucketIO**, designed as a telephone directory: white pages, yellow pages, rates, directory assistance, and an order form on the back cover. It scrolls smoothly with **Lenis**, and the cover opens in 3D through **GSAP ScrollTrigger**.

This README is written for an AI CLI agent (Claude Code or similar) that will turn the prototype into production code.

---

## 1. What the product is (source of truth for copy)

BucketIO is a local, self-hosted contact store (SQLite) that sits **in front of Treg** (treg.to, a priced API catalog for find/verify). Given *Name + Company*, it does four things, in order:

1. **In the bucket?** If the person is already stored, it returns the result for **$0**.
2. **House style known?** If the company's email format is on file, BucketIO builds the address and asks Treg only to **verify** (from $0.0019).
3. **Stranger company.** Otherwise it asks Treg to **find** (from $0.00483), stores the result, and **learns the format** so the next person at that company is cheap.
4. **Nobody found.** It **pencils in** the most probable address from learned patterns (unverified, $0).

**Laya** (`convaiinnovations/laya`) is a **scorer and tie-breaker, never a generator**. It only acts in the gray zone (format confidence under .80, and pencilled guesses). It is rolled out in stages: Off → Shadow (its picks are logged, not used) → Active (its picks settle ties).

Treg rates in the copy are the lowest listed per job on treg.to as of **Sept 2026**. Re-check them before launch.

---

## 2. Files

| Path | What it is |
|---|---|
| `BucketIO Directory.dc.html` | The whole prototype as one Design Component: the template (markup, inline styles) plus the logic class (`class Component`) plus props. |
| `fonts/` | Basteleur Bold/Moonlight (`.otf`), PicNic (`.woff2/.woff`). Montagu Slab and Space Mono load from Google Fonts. |
| `image-slot.js` | Drop-in image placeholder web component, used for two airbrush art plates. |
| `research-notes.md` | Research: Lenis + GSAP integration, Treg pricing, phone-book typography. |
| `uploads/` | Mood references (Ship to Shore cover, Grushkin airbrush board, poem spread, Sam Goody card, GAO Dumpling site, Herman Miller catalog, Japanese book spread). |

---

## 3. Stack

- **Lenis 1.3.26** (`https://unpkg.com/lenis@1.3.26/dist/lenis.min.js` plus `lenis.css`)
- **GSAP 3.15 + ScrollTrigger** (`https://cdn.jsdelivr.net/npm/gsap@3.15/dist/…`). GSAP is 100% free, including its bonus plugins.
- Integration (keep it exactly like this):

```js
const lenis = new Lenis({ lerp: 0.08, allowNestedScroll: true });
lenis.on('scroll', ScrollTrigger.update);
gsap.ticker.add(t => lenis.raf(t * 1000));
gsap.ticker.lagSmoothing(0);
```

- Recommended production port: **Vite + React** (or Next.js), with `lenis`, `gsap`, and `@gsap/react` (`useGSAP` for cleanup). Build one component per section (see §6). Keep the lookup simulation in a pure module, `lib/directory.ts`.
- Do **not** use GSAP `pin` on React-managed nodes. The hero uses a **tall section with a `position: sticky` stage**, and ScrollTrigger scrubs over the section. This avoids pin-spacer DOM mutation.

---

## 4. Design system

This is built on the *Editorial — Personal Magazine* system (paper and ink, rules not boxes, no shadows, no rounded corners, no emoji, no icon sets). Art direction is layered on top of it: phone book, GAO Dumpling (heavy caps, label bars, menu columns), and Ship to Shore / Grushkin (airbrush, blue and black lettering).

### Type
| Role | Face | Notes |
|---|---|---|
| Headlines, body, listings | **Montagu Slab**, opsz **16**, weight **400** | Set with `font-variation-settings:'opsz' 16` on the root. Headlines are ALL CAPS, line-height 0.82–0.9, letter-spacing −0.025em. Surnames in listings use `font-weight:700`. |
| Cover A title, poem lines | **Basteleur** Bold 700 / Moonlight 300 | Only for "literary" moments. |
| Micrographics | **Space Mono** 400/700 | Uppercase, +0.14–0.18em, 10–11px: folios, kickers, codes, prices. |
| Annotations | **PicNic** | Vermilion margin notes; non-photo-blue "pencil" for guesses. |

### Color tokens (literal hex, used inline)
| Token | Hex | Use |
|---|---|---|
| paper | `#F1ECE0` | Default page (story, rates, assistance) |
| paper-bright | `#FBFAF6` | White Pages, book pages, ticket, back cover |
| paper-news (mat board) | `#E7E0D0` | Hero and back-cover board |
| paper-stone | `#DADFD9` | Operator |
| ink / ink-2 / ink-3 / ink-4 / ink-5 | `#1B1813` `#38342C` `#6B655A` `#9C9587` `#C9C2B2` | Text ramp. Use ink-4 and ink-5 only for decoration or disabled states. |
| vermilion / vermilion-2 | `#C2412A` / `#A6321F` | Stamps, step numbers, CTA, active nav |
| pine | `#2D5A3D` | Announcement bar |
| **directory yellow** | `#EDD351` | Yellow Pages section, Cover B |
| **cyan** | `#5CB8C9` | Giant "LEARN IT" / "411" graphics only (decorative, `aria-hidden`) |
| **print blue** | `#4F7FB8` | Blue display lettering on Cover A |
| **pencil blue** | `#3F6EA5` | Guessed (PG) addresses, production notes. It passes 4.5:1 on paper. |
| sea (airbrush) | `#9EC0E3 → #7DA6D2` | Cover A sprayed sea |

### Color rhythm (top → bottom)
1. Mat board `#E7E0D0` (hero, front cover)
2. Paper `#F1ECE0` (How a lookup is placed)
3. Paper `#F1ECE0` with a 4px ink rule (Rates)
4. **Paper-bright `#FBFAF6`** (White Pages)
5. **Yellow `#EDD351`** (Yellow Pages)
6. Paper `#F1ECE0` (Directory Assistance)
7. **Stone `#DADFD9`** (Operator)
8. Mat board with a paper-bright panel (Back cover)

The rhythm is warm, warm, warm, white, **loud**, warm, cool, warm. Keep yellow to one section plus Cover B.

### Rules and components
- Rules: 1px `rgba(27,24,19,.16)` hairline, 1.5px ink, 2px section, **4px ink bottom rule** (GAO menu), dashed `rgba(27,24,19,.34)` in tables, dotted leaders in listings.
- **Label bar**: ink background, paper text, caps, `padding:5–7px`. Examples: "$0.00 PER CALL" and trade headings.
- **Display ad**: 3px ink border (the only boxed element besides the coupon and the ticket's candidate table).
- Buttons are square: solid ink (primary in-page), vermilion (back-cover CTA), or outline (header). Hover darkens the button; hover on text links turns them vermilion.

---

## 5. Motion spec

| Moment | Implementation |
|---|---|
| Smooth scroll | Lenis, lerp 0.08 (a prop). It honors reduced motion by default. |
| **Cover opens (3D)** | The hero is 240vh tall with a 100vh sticky stage (`perspective:2400px`). The book uses `transform-style:preserve-3d`. The cover rotates `rotateY 0 → −178°` around its left edge. The book moves `xPercent 0 → 50` (desktop ≥820px) so the open spread sits centred. The front-face shade goes 0 → .55 and the back-face shade .45 → 0. Everything is scrubbed (`scrub:.8`, `end:'bottom bottom'`). Setting the prop `coverOpens: On click` makes the hero 100vh and runs a 1.6s tween on click. |
| Header | Hidden during the hero. It fades in once the section after the hero reaches `top 80px`. |
| Section tracking | ScrollTrigger per `[data-sec]` sets the active nav item and the folio. |
| Reveals | `[data-reveal]` and `[data-line]` fade in with an 18px rise over 0.9–1.1s (`power2.out`), once. |
| Marquees | `[data-marquee]` moves `xPercent` 0 → −20, scrubbed across the viewport; `="r"` reverses it. |
| Ticket | Steps reveal every 520ms. Then the stamp lands (scale 1.6 → 1, rotation −16° → −6°, 0.4s). |
| New listing | A highlight wash `rgba(128,90,0,.34)` fades out over 3s on `[data-new="true"]`. |
| Tear-off CTA | Copies the command, tugs the coupon twice, then drops it (y+220, rotate 11°, fade) and reveals the "Copied." block. |

No bounce, no spring, no glow. Easing is `power2.inOut` / `power2.out`.

---

## 6. Sections (build as components)

1. **Hero / Cover**: announcement bar, crop marks, mechanical labels, an A/B cover switch, the 3D book, pencil production notes, and a scroll hint.
   - Cover A "Name to Address" (Ship to Shore): CSS airbrush of sky haze, sea, streaks, and shore mass, with grain.
   - Cover B "The Bucket Directory" (Yellow Pages / GAO): yellow stock, cyan "411", vermilion "$0" square.
   - The inside cover holds *How to use this directory* and the *Key to abbreviations* (KN/VF/FD/PG). Page 1 holds the clickable Contents.
2. **How a lookup is placed (pp. 2–3)**: a poem-spread layout. Staggered indents, Basteleur Moonlight lines, vermilion step labels, PicNic margin notes, a stapled gutter, and "in pencil" as cascading letters.
3. **Rates (pp. 4–5)**: a marquee, then four GAO-style menu columns (Already known, House style known, A stranger company, Nobody found), then the Treg source footnote.
4. **White Pages (pp. 6–7)**: A–Z index; a two-page spread with guide words and folios; CSS `columns: 2 220px` with column rules. Each entry has a bold uppercase surname, a first name, the company, dotted leaders, the email, and a code. PG entries are set in PicNic pencil blue. A "Not listed? Dial 4-1-1" ad links to the demo.
5. **Yellow Pages (pp. 8–9)**: a cyan "LEARN IT" marquee, then a Herman-Miller-style catalog with trade label bars on the left and company cards (domain, `pattern@`, times seen, confidence, gray-zone flag). Two display ads follow, plus "House styles, by count".
6. **Directory Assistance (pp. 10–11)**: a live simulated lookup. The form has six ordered presets that exercise every branch. The toll ticket shows the four steps with costs, a Rules-vs-Laya candidate table, the total against a cold find, a "Listed as" line, and a stamp. A Statement of charges follows. Results write back into the White and Yellow Pages.
7. **The Operator (p. 12)**: explains Laya, with a Shadow/Active switch that the demo actually uses, the Off/Shadow/Active ladder, a switchboard log of gray-zone decisions, and image-slot Fig. 01.
8. **Back cover**: the headline "Keep one by the phone", image-slot Fig. 02, the tear-off order coupon (the **primary CTA**, which copies the install command), and a colophon.

---

## 7. Lookup simulation (port to `lib/directory.ts`)

- `companies[]`: `{ id, name, domain, pattern, seen, conf, trade, truth? }`. `truth` is the real format when the cached one is wrong. Riverside Print is the example: cached `last@`, actually `first.last@`.
- `people[]`: `{ id, last, first, co, coName, email, code: FD|VF|PG }`, sorted by slug(last) and then slug(first). In the seed, the first person per company is `FD`, the rest are `VF`, and companies with confidence under .80 get `PG`.
- Patterns: `first.last, flast, first, first_last, first.l, f.last, firstl, last, lastf, firstlast`.
- `TREG` world (companies Treg can find): Orchard Bank, Kestrel Air, Union Ice, Calder & Voss. Any other unknown company falls to the pencil branch.
- Candidate scoring: **rules** come from the known confidence or the pattern distribution. **Laya** is a deterministic heuristic that stands in for the model: it favours `truth` for gray known companies, and `first@` for small shops (studio, coffee, books, cartography, press, &).
- Verify loop: verify candidates in the active ranking's order until one matches `truth`. Each verify costs $0.0019.
- Constants: `FIND = 0.00483`, `VERIFY = 0.0019`.
- **In production**, replace the simulation with real endpoints: `GET /lookup?name=&company=` returning `{steps[], total, result}`, `GET /people`, `GET /companies`. Keep the same trace shape so the ticket UI is unchanged.

---

## 8. Props / tweaks

| Prop | Default | Effect |
|---|---|---|
| `cover` | Ship to Shore | Cover A or Cover B (an in-page switch also exists) |
| `coverOpens` | On scroll | On scroll (scrubbed 3D) or On click |
| `smoothness` | 0.08 | Lenis lerp |
| `layaMode` | Shadow | Default Laya mode for the demo |
| `marginNotes` | true | Shows or hides the PicNic annotations |
| `installCommand` | `bucketio serve --db ./bucket.sqlite` | **Placeholder**. Replace with the real command. |
| `repoUrl` | `https://github.com/` | **Placeholder**. Replace with the real repo URL. |

---

## 9. Accessibility and responsiveness

- Text meets 4.5:1 contrast, except giant decorative type (cyan on yellow, marked `aria-hidden`) and disabled or idle states.
- Below 820px the header nav, pencil notes, and poem gutter are hidden, and the book doesn't shift. Layouts use flex-wrap, grid `auto-fit`, `clamp()`, and container-query units (`cqw`) inside the book faces.
- Focus style is a 1px vermilion outline with a 3px offset. All controls are `<button>` or `<input>` with labels.
- Reduced motion: Lenis stops smoothing automatically. **TODO:** wrap the GSAP reveals and book scrub in `gsap.matchMedia('(prefers-reduced-motion: no-preference)')` and show the book open statically otherwise.

---

## 10. TODO for the agent

1. Port to Vite + React components following §6. Move all inline hex values into CSS variables named in §4.
2. Replace the `installCommand` and `repoUrl` placeholders; confirm the real CLI.
3. Wire the real BucketIO API (§7); keep the simulation as the offline fallback.
4. Put the user's airbrush art into the Fig. 01 and Fig. 02 plates (and optionally the covers).
5. Add the reduced-motion branch (§9) and a `prefers-color-scheme`-agnostic print stylesheet.
6. Self-host the fonts (Montagu Slab, Space Mono) for production. Check the Basteleur and PicNic licences.
7. Re-verify the Treg prices and date in the Rates footnote.
8. Lighthouse: aim for 95+ on performance. Animate only `transform` and `opacity`, apply `will-change` just to the cover and book during the hero, and lazy-load the plates.

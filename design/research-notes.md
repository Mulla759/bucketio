# BucketIO Directory — research notes

## Angle
A telephone directory, not a landing page. People = **White Pages**; learned company email formats = **Yellow Pages** (the Sam Goody yellow/cyan card). Cover borrows *Ship to Shore* (spaced black caps, blue secondary line, airbrushed sea). The lookup story is set like the scattered poem spread, with a stapled gutter. The Grushkin city: lit windows = contacts already known ($0).

## Lenis (darkroomengineering/lenis, v1.3.26)
- `<script src="https://unpkg.com/lenis@1.3.26/dist/lenis.min.js">` + `https://unpkg.com/lenis@1.3.26/dist/lenis.css`
- With GSAP: `lenis.on('scroll', ScrollTrigger.update); gsap.ticker.add(t => lenis.raf(t*1000)); gsap.ticker.lagSmoothing(0);`
- Options: `anchors`, `lerp` (0.1), `duration` (1.2), `respectReducedMotion` (default true). Use `data-lenis-prevent` on nested scroll areas.
- Limitation: smoothing stops over iframes, since they don't forward wheel events.

## GSAP (greensock/gsap)
- CDN: `https://cdn.jsdelivr.net/npm/gsap@3.15/dist/gsap.min.js`, plus `ScrollTrigger.min.js` from the same dist.
- Fully free (Webflow), bonus plugins included (SplitText, MorphSVG), even for commercial use.
- Book = 3D transforms (rotateY with perspective, transform-origin at the spine). They're GPU-composited, and ScrollTrigger scrubs them.

## Treg (treg.to)
- A catalog/router of API providers for agents. Priced per call from a prepaid balance at 0% markup; a team's own keys always win.
- Email **find**: 12 providers, from about $0.00483 per success. Email **verify**: 8 verifiers, from $0.0019 per call.
- Company format call returns patterns such as first.last@, first@, flast@, first_last@, each with a count/confidence. A pattern plus a name gives a probable address, and it is normally followed by verify.
- "Unknown" or catch-all makes up about a fifth of a real B2B list.

## Phone-book typography
- Bell Centennial (Matthew Carter, 1978, AT&T) is the directory face. It isn't licensed here, so listings use the DS Helvetica stack with bold surnames and Space Mono for addresses and numbers.
- Conventions: 4 columns, hairline column rules, guide words at the page head (ABBOTT — ADLER), leader dots to a right-aligned number, a thumb index on the fore-edge, folios.

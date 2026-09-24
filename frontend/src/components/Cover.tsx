import { useCallback, useRef } from "react";
import type { KeyboardEvent } from "react";
import { useGSAP } from "@gsap/react";
import { gsap, prefersReducedMotion, scrollToY, useVanta } from "../lib/motion";
import { Coupon } from "./Coupon";
import { Logo } from "./Logo";

export interface CoverProps {
  agentPrompt: string;
  peopleCount: number;
  coCount: number;
  year: number;
  onNav: (id: string) => void;
}

const SERIF = "var(--serif)";
const MONO = "var(--mono)";

/* The scrub finishes turning the cover at ~84% of the hero's scroll range. */
const OPEN_AT = 0.84;

export function Cover({ agentPrompt, peopleCount, coCount, year, onNav }: CoverProps) {
  const heroRef = useRef<HTMLElement | null>(null);
  const bookRef = useRef<HTMLDivElement | null>(null);
  const coverRef = useRef<HTMLDivElement | null>(null);
  const shadeFrontRef = useRef<HTMLDivElement | null>(null);
  const shadeBackRef = useRef<HTMLDivElement | null>(null);
  const hintRef = useRef<HTMLDivElement | null>(null);
  const bigRef = useRef<HTMLDivElement | null>(null);
  const stampRef = useRef<HTMLDivElement | null>(null);
  const vantaRef = useRef<HTMLDivElement | null>(null);

  useVanta(vantaRef, "fog");

  /* Clicking the closed cover scrolls the hero open (the scrub does the rest);
     once it is open, a second click carries on to the next section. */
  const openCover = useCallback(() => {
    const hero = heroRef.current;
    if (!hero) return;
    const top = hero.getBoundingClientRect().top + window.scrollY;
    const range = Math.max(0, hero.offsetHeight - window.innerHeight);
    const opened = top + range * OPEN_AT;
    scrollToY(window.scrollY < opened - 12 ? opened : top + range);
  }, []);

  const onCoverKey = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openCover();
      }
    },
    [openCover],
  );

  useGSAP(
    () => {
      const hero = heroRef.current;
      const book = bookRef.current;
      const cover = coverRef.current;
      if (!hero || !book || !cover) return;

      if (prefersReducedMotion()) {
        gsap.set(cover, { rotateY: -178 });
        gsap.set(book, { xPercent: window.innerWidth >= 820 ? 50 : 0 });
        gsap.set(shadeBackRef.current, { opacity: 0 });
        gsap.set(shadeFrontRef.current, { opacity: 0 });
        return;
      }

      gsap
        .timeline({ defaults: { ease: "power3.out" } })
        .from(book, { y: 40, autoAlpha: 0, duration: 1.1 })
        .from("[data-intro]", { y: 14, autoAlpha: 0, duration: 0.8, stagger: 0.12 }, 0.4)
        .from(bigRef.current, { xPercent: -40, autoAlpha: 0, duration: 1.4 }, 0.5)
        .from(stampRef.current, { scale: 1.5, rotate: -16, autoAlpha: 0, duration: 0.5 }, 1.15);

      const shift = () => (window.innerWidth >= 820 ? 50 : 0);
      gsap
        .timeline({
          defaults: { ease: "none" },
          scrollTrigger: {
            trigger: hero,
            start: "top top",
            end: "bottom bottom",
            scrub: 0.8,
            invalidateOnRefresh: true,
          },
        })
        .to(hintRef.current, { autoAlpha: 0, duration: 0.08 }, 0)
        .to(cover, { rotateY: -178, duration: 1, ease: "power2.inOut" }, 0.04)
        .to(book, { xPercent: shift, duration: 1, ease: "power2.inOut" }, 0.04)
        .to(shadeFrontRef.current, { opacity: 0.55, duration: 0.48, ease: "power1.in" }, 0.04)
        .to(shadeBackRef.current, { opacity: 0, duration: 0.5, ease: "power1.out" }, 0.54)
        .to(bigRef.current, { yPercent: -18, duration: 0.6 }, 0.04)
        .to({}, { duration: 0.2 });
    },
    { scope: heroRef },
  );

  return (
    <section ref={heroRef} data-hero data-screen-label="Cover" style={{ position: "relative", height: "240vh", background: "var(--paper-news)" }}>
      <div className="cover-stage">
        <div ref={vantaRef} className="vanta-layer" aria-hidden="true" />

        <div className="cover-board">
          <div
            ref={bookRef}
            data-book
            className="book"
            style={{ cursor: "default" }}
          >
            <div style={{ position: "absolute", top: 4, bottom: -6, right: -8, width: 8, background: "repeating-linear-gradient(90deg,#D6CDB9 0 1px,#F4F0E6 1px 2px)", transform: "translateZ(-1px)" }} />
            <div style={{ position: "absolute", left: 4, right: -8, bottom: -8, height: 8, background: "repeating-linear-gradient(180deg,#D6CDB9 0 1px,#F4F0E6 1px 2px)", transform: "translateZ(-1px)" }} />

            {/* page 1, revealed as the cover opens */}
            <div
              style={{
                position: "absolute",
                inset: 0,
                background: "var(--paper-bright)",
                containerType: "inline-size",
                padding: "9% 8.5%",
                display: "flex",
                flexDirection: "column",
                transform: "translateZ(0)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", font: `400 max(7px,1.6cqw)/1 ${MONO}`, letterSpacing: ".16em", textTransform: "uppercase", color: "var(--ink-3)" }}>
                <span>Page 1</span>
                <span>Contacts · formats · Treg</span>
              </div>
              <div style={{ marginTop: "6cqw", font: `400 8.4cqw/.92 ${SERIF}`, letterSpacing: "-.02em", textTransform: "uppercase" }}>
                Look anyone up once. Never pay for them twice.
              </div>
              <p style={{ margin: "4cqw 0 0", font: `400 max(10px,2.8cqw)/1.45 ${SERIF}`, color: "var(--ink-2)" }}>
                BucketIO is a small directory on your own machine that sits in front of Treg. It remembers everyone you’ve looked up, learns how each company writes its addresses, and pays for a find only when it has to.
              </p>
              <div style={{ marginTop: "5cqw", display: "flex", flexDirection: "column", gap: "2.4cqw" }}>
                <button type="button" className="btn-ink" onClick={() => onNav("setup")} style={{ padding: "3cqw", font: `700 max(10px,2.6cqw)/1 ${SERIF}` }}>
                  Set up the directory
                </button>
                <button type="button" className="tlink" onClick={() => onNav("docs")} style={{ font: `400 max(10px,2.5cqw)/1 ${SERIF}` }}>
                  Read the docs ↓
                </button>
              </div>
              <div style={{ marginTop: "auto", borderTop: "1px solid var(--ink)", paddingTop: "2cqw", display: "flex", justifyContent: "space-between", gap: "2cqw", font: `400 max(8px,2cqw)/1.3 ${SERIF}`, color: "var(--ink-2)" }}>
                <span>{peopleCount} listings</span>
                <span>{coCount} formats</span>
                <span>$0 per known call</span>
              </div>
            </div>

            {/* the cover itself */}
            <div ref={coverRef} data-cover style={{ position: "absolute", inset: 0, transformOrigin: "0% 50%", transformStyle: "preserve-3d" }}>
              <div
                onClick={openCover}
                onKeyDown={onCoverKey}
                role="button"
                tabIndex={0}
                aria-label="Open the cover"
                style={{ position: "absolute", inset: 0, backfaceVisibility: "hidden", WebkitBackfaceVisibility: "hidden", transform: "translateZ(0.6px)", overflow: "hidden", containerType: "inline-size", boxShadow: "0 26px 54px -26px rgba(20,18,15,.6)", cursor: "pointer" }}
              >
                <div style={{ position: "absolute", inset: 0, background: "var(--yellow)" }}>
                  <div
                    ref={bigRef}
                    data-411
                    aria-hidden="true"
                    style={{ position: "absolute", left: "-3%", bottom: "5%", font: `700 50cqw/.8 ${SERIF}`, letterSpacing: "-.06em", color: "var(--cyan)", whiteSpace: "nowrap" }}
                  >
                    411
                  </div>
                  <div data-intro style={{ position: "absolute", left: "6%", right: "6%", top: "5%", background: "var(--ink)", color: "var(--yellow)", display: "flex", justifyContent: "space-between", gap: "2cqw", padding: "1.3cqw 1.8cqw", font: `700 max(7px,2.1cqw)/1 ${SERIF}`, textTransform: "uppercase" }}>
                    <span>White &amp; yellow pages</span>
                    <span>{peopleCount} listings · {coCount} formats</span>
                  </div>
                  <div data-intro style={{ position: "absolute", left: "6%", right: "6%", top: "13%", font: `700 12.4cqw/.86 ${SERIF}`, letterSpacing: "-.03em", textTransform: "uppercase", color: "var(--ink)" }}>
                    The
                    <br />
                    bucket
                    <br />
                    directory
                  </div>
                  <div data-intro style={{ position: "absolute", left: "6%", top: "48%", maxWidth: "54%", font: `400 max(9px,2.7cqw)/1.25 ${SERIF}`, color: "var(--ink)" }}>
                    Everyone already looked up, and how every company writes its addresses. Local edition, {year}.
                  </div>
                  <div data-intro style={{ position: "absolute", left: "6%", bottom: "5%" }}>
                    <Logo size={22} className="logo-ink" />
                  </div>
                  <div ref={stampRef} data-cstamp style={{ position: "absolute", right: "6%", bottom: "5%", width: "24cqw", height: "24cqw", background: "var(--vermilion)", color: "var(--paper-bright)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "1.4cqw", transform: "rotate(-4deg)" }}>
                    <span style={{ font: `700 9cqw/.9 ${SERIF}`, letterSpacing: "-.04em" }}>$0</span>
                    <span style={{ font: `400 max(6px,1.5cqw)/1.25 ${MONO}`, letterSpacing: ".12em", textTransform: "uppercase", textAlign: "center" }}>
                      Per known
                      <br />
                      call
                    </span>
                  </div>
                  <div style={{ position: "absolute", inset: 0, backgroundImage: "radial-gradient(rgba(20,18,15,.2) .6px,transparent .7px)", backgroundSize: "3px 3px", mixBlendMode: "multiply", opacity: 0.4 }} />
                </div>
                <div ref={shadeFrontRef} data-shade-f style={{ position: "absolute", inset: 0, background: "#141210", opacity: 0, pointerEvents: "none" }} />
              </div>

              {/* inside front cover */}
              <div style={{ position: "absolute", inset: 0, backfaceVisibility: "hidden", WebkitBackfaceVisibility: "hidden", transform: "rotateY(180deg) translateZ(0.6px)", background: "var(--paper)", overflow: "hidden", containerType: "inline-size", boxShadow: "0 26px 54px -26px rgba(20,18,15,.6)" }}>
                <div style={{ position: "absolute", inset: 0, padding: "9% 8.5%", display: "flex", flexDirection: "column", gap: "3.2cqw" }}>
                  <div style={{ font: `400 max(7px,1.6cqw)/1 ${MONO}`, letterSpacing: ".16em", textTransform: "uppercase", color: "var(--ink-3)" }}>Inside front cover</div>
                  <div style={{ font: `400 7.4cqw/.92 var(--display)`, letterSpacing: "-.01em" }}>
                    How to use
                    <br />
                    this directory
                  </div>
                  <p style={{ margin: 0, font: `400 max(9px,2.6cqw)/1.42 ${SERIF}`, color: "var(--ink-2)" }}>
                    Ask for a person by name and company. BucketIO looks in its own pages first, then at the company’s house style, and only then places a paid call to Treg. Whatever comes back is written down, so nobody is looked up twice.
                  </p>
                  <div style={{ borderTop: "1.5px solid var(--ink)", paddingTop: "2.2cqw", font: `700 max(7px,1.7cqw)/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase" }}>
                    Key to abbreviations
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "1.6cqw", font: `400 max(8.5px,2.4cqw)/1.3 ${SERIF}` }}>
                    <div style={{ display: "flex", gap: "3cqw", paddingBottom: "1.6cqw", borderBottom: "1px dashed var(--rule-dash)" }}>
                      <b style={{ width: "6cqw", flex: "none" }}>KN</b>
                      <span>Known — answered from the bucket, $0.00.</span>
                    </div>
                    <div style={{ display: "flex", gap: "3cqw", paddingBottom: "1.6cqw", borderBottom: "1px dashed var(--rule-dash)" }}>
                      <b style={{ width: "6cqw", flex: "none" }}>VF</b>
                      <span>Verified — built from the house style, checked by Treg.</span>
                    </div>
                    <div style={{ display: "flex", gap: "3cqw", paddingBottom: "1.6cqw", borderBottom: "1px dashed var(--rule-dash)" }}>
                      <b style={{ width: "6cqw", flex: "none" }}>FD</b>
                      <span>Found — Treg found them; the style was learned.</span>
                    </div>
                    <div style={{ display: "flex", gap: "3cqw", color: "var(--pencil)" }}>
                      <b style={{ width: "6cqw", flex: "none" }}>PG</b>
                      <span>Pencilled in — the most probable address, unverified.</span>
                    </div>
                  </div>
                  <div style={{ marginTop: "auto", display: "flex", alignItems: "baseline", gap: "2cqw", font: `400 max(8px,2.2cqw)/1 ${SERIF}`, color: "var(--ink-2)" }}>
                    <span style={{ whiteSpace: "nowrap" }}>This directory belongs to</span>
                    <span style={{ flex: 1, borderBottom: "1px solid var(--ink)", font: `400 max(11px,3.6cqw)/1 var(--pencil-face)`, color: "var(--pencil)", paddingLeft: "2cqw" }}>my own machine</span>
                  </div>
                </div>
                <div ref={shadeBackRef} data-shade-b style={{ position: "absolute", inset: 0, background: "#141210", opacity: 0.45, pointerEvents: "none" }} />
              </div>
            </div>
          </div>
        </div>

        <div ref={hintRef} data-hint className="cover-hint">
          <Coupon
            compact
            command={agentPrompt}
            voidColor="paper-news"
            serial="NO. 0001"
            buttonLabel="Tear off & copy"
          />
          <div className="cover-hint-row">
            <button type="button" className="tlink" onClick={() => onNav("docs")}>
              Read the docs ↓
            </button>
            <span className="cover-hint-text">Click the cover or scroll ↓</span>
          </div>
        </div>
      </div>
    </section>
  );
}

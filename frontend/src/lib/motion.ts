/* Motion: Lenis for the scroll, GSAP ScrollTrigger for the scrubbed moments,
   Vanta for the two decorative atmospheres. Everything here is opt-out via
   prefers-reduced-motion, and Vanta is lazy + paused off-screen. */

import { useCallback, useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import type { RefObject } from "react";

gsap.registerPlugin(ScrollTrigger);

export { gsap, ScrollTrigger };

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

let activeLenis: Lenis | null = null;

/** Smooth scroll, wired to ScrollTrigger exactly as the handoff prescribes. */
export function useLenis(lerp = 0.08): void {
  useEffect(() => {
    if (prefersReducedMotion()) return;
    const lenis = new Lenis({ lerp, allowNestedScroll: true, anchors: true });
    activeLenis = lenis;
    const onScroll = () => ScrollTrigger.update();
    lenis.on("scroll", onScroll);
    const tick = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    return () => {
      gsap.ticker.remove(tick);
      lenis.destroy();
      activeLenis = null;
    };
  }, [lerp]);
}

export function scrollToId(id: string, offset = -62): void {
  const target = document.getElementById(id);
  if (!target) return;
  if (activeLenis) {
    activeLenis.scrollTo(target, { offset, duration: 1.6 });
    return;
  }
  const top = target.getBoundingClientRect().top + window.scrollY + offset;
  window.scrollTo({ top, behavior: prefersReducedMotion() ? "auto" : "smooth" });
}

export function scrollToTop(): void {
  if (activeLenis) {
    activeLenis.scrollTo(0, { duration: 1.4 });
    return;
  }
  window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" });
}

/** Scroll to an absolute document position (the cover's click-to-open). */
export function scrollToY(target: number, duration = 1.6): void {
  if (activeLenis) {
    activeLenis.scrollTo(target, { duration });
    return;
  }
  window.scrollTo({ top: target, behavior: prefersReducedMotion() ? "auto" : "smooth" });
}

/** Which page of the directory is on the desk: drives the nav and the folio. */
export function useSectionTracking(): { section: string; folio: string } {
  const [state, setState] = useState({ section: "", folio: "" });

  useEffect(() => {
    const sections = Array.from(document.querySelectorAll<HTMLElement>("[data-sec]"));
    if (!sections.length) return;
    const triggers = sections.map((element) =>
      ScrollTrigger.create({
        trigger: element,
        start: "top 90px",
        end: "bottom 90px",
        onToggle: (self) => {
          if (self.isActive) {
            setState({ section: element.id, folio: element.dataset.folio ?? "" });
          }
        },
      }),
    );
    return () => {
      triggers.forEach((trigger) => trigger.kill());
    };
  }, []);

  return state;
}

/** Reveals. Returns a function the app can call again once data has landed. */
export function useReveals(): () => void {
  const tweens = useRef<gsap.core.Tween[]>([]);

  const run = useCallback(() => {
    if (prefersReducedMotion()) return;
    document.querySelectorAll<HTMLElement>("[data-reveal]:not([data-revealed])").forEach((element) => {
      element.dataset.revealed = "1";
      tweens.current.push(
        gsap.from(element, {
          autoAlpha: 0,
          y: 18,
          duration: 0.9,
          ease: "power2.out",
          scrollTrigger: { trigger: element, start: "top 90%", once: true },
        }),
      );
    });
    document.querySelectorAll<HTMLElement>("[data-line]:not([data-revealed])").forEach((element) => {
      element.dataset.revealed = "1";
      tweens.current.push(
        gsap.from(element, {
          autoAlpha: 0,
          y: 14,
          duration: 1.1,
          ease: "power2.out",
          scrollTrigger: { trigger: element, start: "top 92%", once: true },
        }),
      );
    });
  }, []);

  useEffect(() => {
    run();
    return () => {
      tweens.current.forEach((tween) => tween.kill());
      tweens.current = [];
      document.querySelectorAll<HTMLElement>("[data-revealed]").forEach((element) => {
        delete element.dataset.revealed;
        gsap.set(element, { clearProps: "opacity,visibility,transform" });
      });
    };
  }, [run]);

  return run;
}

/** The header stays out of the way until the cover is past. */
export function useHeaderReveal(
  headerRef: RefObject<HTMLElement | null>,
  afterHeroRef: RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    const header = headerRef.current;
    const afterHero = afterHeroRef.current;
    if (!header || !afterHero) return;
    if (prefersReducedMotion()) {
      gsap.set(header, { autoAlpha: 1, y: 0 });
      return;
    }
    const trigger = ScrollTrigger.create({
      trigger: afterHero,
      start: "top 80px",
      onEnter: () => gsap.to(header, { autoAlpha: 1, y: 0, duration: 0.5, ease: "power2.out" }),
      onLeaveBack: () => gsap.to(header, { autoAlpha: 0, y: -10, duration: 0.3 }),
    });
    return () => {
      trigger.kill();
    };
  }, [headerRef, afterHeroRef]);
}

/** The shapes a sheet can arrive in: leaning back from the foot, swinging in
    from either hinge, or falling flat from the head. They cycle so the run of
    pages never reads as the same move twice. */
const TURN_VARIANTS: gsap.TweenVars[] = [
  { scale: 0.92, rotateX: 7, transformOrigin: "50% 100%" },
  { scale: 0.9, rotateY: -4, xPercent: 1, transformOrigin: "0% 50%" },
  { scale: 0.94, rotateX: -5, transformOrigin: "50% 0%" },
  { scale: 0.9, rotateY: 4, xPercent: -1, transformOrigin: "100% 50%" },
];

/** The pages after the cover. Each sheet comes in smaller and tilted, then
    zooms to size as it takes the viewport — one scrubbed trigger per page,
    transform-only, off under reduced motion. */
export function usePageTurns(): void {
  useEffect(() => {
    if (prefersReducedMotion()) return;
    const pages = Array.from(
      document.querySelectorAll<HTMLElement>("[data-after-hero] > section"),
    );
    if (!pages.length) return;
    const triggers = pages.map((page, index) => {
      const from = TURN_VARIANTS[index % TURN_VARIANTS.length];
      const tween = gsap.fromTo(
        page,
        { transformPerspective: 2200, ...from },
        {
          scale: 1,
          rotateX: 0,
          rotateY: 0,
          xPercent: 0,
          ease: "none",
          scrollTrigger: {
            trigger: page,
            start: "top bottom",
            end: "top 12%",
            scrub: 0.6,
            invalidateOnRefresh: true,
          },
        },
      );
      return tween.scrollTrigger ?? null;
    });
    return () => {
      triggers.forEach((trigger) => trigger?.kill());
      pages.forEach((page) => gsap.set(page, { clearProps: "transform" }));
    };
  }, []);
}

/** A highlight wash for freshly written listings. */
export function washNew(scope: HTMLElement | Document = document): void {
  if (prefersReducedMotion()) return;
  const elements = scope.querySelectorAll<HTMLElement>('[data-new="true"]');
  if (!elements.length) return;
  gsap.fromTo(
    elements,
    { backgroundColor: "rgba(128,90,0,0.34)" },
    { backgroundColor: "rgba(128,90,0,0)", duration: 3, delay: 0.2, ease: "power1.in", clearProps: "backgroundColor" },
  );
}

export function refreshTriggers(): void {
  ScrollTrigger.refresh();
}

/* ---------- Vanta ---------- */

export type VantaKind = "fog" | "net" | "waves" | "clouds";

interface VantaEffect {
  destroy: () => void;
}

type VantaFactory = (options: Record<string, unknown>) => VantaEffect;

/* Static map so Vite can code-split each effect (and three) into its own chunk. */
const VANTA_LOADERS: Record<VantaKind, () => Promise<{ default: VantaFactory }>> = {
  fog: () => import("vanta/dist/vanta.fog.min.js") as Promise<{ default: VantaFactory }>,
  net: () => import("vanta/dist/vanta.net.min.js") as Promise<{ default: VantaFactory }>,
  waves: () => import("vanta/dist/vanta.waves.min.js") as Promise<{ default: VantaFactory }>,
  clouds: () => import("vanta/dist/vanta.clouds.min.js") as Promise<{ default: VantaFactory }>,
};

const VANTA_OPTIONS: Record<VantaKind, Record<string, unknown>> = {
  fog: {
    baseColor: 0xe7e0d0,
    highlightColor: 0xfbfaf6,
    midtoneColor: 0xdadfd9,
    lowlightColor: 0xc9c2b2,
    blurFactor: 0.7,
    zoom: 0.9,
    speed: 0.8,
  },
  net: {
    color: 0x5cb8c9,
    backgroundColor: 0xf1ece0,
    points: 9,
    maxDistance: 24,
    spacing: 18,
    showDots: false,
    speed: 1,
  },
  waves: {
    color: 0x7da6d2,
    shininess: 40,
    waveHeight: 16,
    waveSpeed: 0.75,
    zoom: 0.9,
  },
  clouds: {
    backgroundColor: 0xe7e0d0,
    skyColor: 0xf1ece0,
    cloudColor: 0xd6cdb9,
    cloudShadowColor: 0x9c9587,
    sunColor: 0xedd351,
    speed: 0.6,
  },
};

/**
 * Mount a Vanta effect into a container. The WebGL context is only created
 * when the container scrolls near the viewport, and never for reduced motion.
 */
export function useVanta(
  ref: RefObject<HTMLElement | null>,
  kind: VantaKind,
  overrides: Record<string, unknown> = {},
): void {
  const overridesRef = useRef(overrides);
  overridesRef.current = overrides;

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (prefersReducedMotion()) return;
    if (window.matchMedia("(max-width: 640px)").matches) return;

    let effect: VantaEffect | null = null;
    let cancelled = false;
    let observer: IntersectionObserver | null = null;

    const start = async () => {
      try {
        const [mod, three] = await Promise.all([VANTA_LOADERS[kind](), import("three")]);
        if (cancelled) return;
        const factory = (mod.default ?? mod) as VantaFactory;
        effect = factory({
          el: element,
          THREE: three,
          ...VANTA_OPTIONS[kind],
          ...overridesRef.current,
        });
      } catch {
        effect = null;
      }
    };

    observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer?.disconnect();
          observer = null;
          void start();
        }
      },
      { rootMargin: "240px" },
    );
    observer.observe(element);

    return () => {
      cancelled = true;
      observer?.disconnect();
      effect?.destroy();
    };
  }, [ref, kind]);
}

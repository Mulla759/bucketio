/* A tear-off coupon strip: the setup line printed on yellow stock, with a
   perforated edge and a stub. Clicking "Tear off & copy" copies the command,
   tugs the coupon twice and drops it, then shows the kept stub. */

import { useCallback, useRef, useState } from "react";
import { gsap, prefersReducedMotion } from "../lib/motion";
import "../styles/coupon.css";
import { BucketMark } from "./Logo";

export interface CouponProps {
  command: string;
  note?: string;
  stub?: string;
  serial?: string;
  buttonLabel?: string;
  onCopied?: () => void;
  compact?: boolean;
  /** Background the notches are punched out of. */
  voidColor?: "paper-bright" | "paper-news" | "paper";
  className?: string;
}

function fallbackCopy(text: string): void {
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  } catch {
    /* clipboard unavailable: the command stays selectable on the page */
  }
}

export function copyText(text: string): void {
  try {
    if (navigator.clipboard) {
      void navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
      return;
    }
  } catch {
    /* fall through */
  }
  fallbackCopy(text);
}

export function Coupon({
  command,
  note = "No expiry. Redeemable on your own machine.",
  stub = "FREE",
  serial = "NO. 0001",
  buttonLabel = "Tear off & copy",
  onCopied,
  compact = false,
  voidColor = "paper-bright",
  className,
}: CouponProps) {
  const [torn, setTorn] = useState(false);
  const [copied, setCopied] = useState(false);
  const couponRef = useRef<HTMLDivElement>(null);

  const tear = useCallback(() => {
    copyText(command);
    setCopied(true);
    onCopied?.();
    const element = couponRef.current;
    if (!element || prefersReducedMotion()) {
      setTorn(true);
      return;
    }
    gsap
      .timeline({ onComplete: () => setTorn(true) })
      .to(element, { y: 3, rotate: 0.6, duration: 0.12, ease: "power1.out", transformOrigin: "100% 0%" })
      .to(element, { y: 2, rotate: -0.4, duration: 0.1 })
      .to(element, { y: 220, x: 60, rotate: 11, autoAlpha: 0, duration: 1, ease: "power2.in" });
  }, [command, onCopied]);

  if (torn) {
    return (
      <div className={`coupon-kept coupon-void-${voidColor} ${className ?? ""}`.trim()}>
        <span className="micro micro-sm">Coupon kept</span>
        <code className="coupon-kept-cmd">$ {command}</code>
        <span className="micro micro-sm micro-verm">{copied ? "Copied ✓" : ""}</span>
        <span className="coupon-kept-actions">
          <button type="button" className="tlink" onClick={() => copyText(command)}>
            Copy again
          </button>
          <button type="button" className="tlink" onClick={() => setTorn(false)}>
            Reprint
          </button>
        </span>
      </div>
    );
  }

  return (
    <div className={`coupon-strip coupon-void-${voidColor} ${compact ? "is-compact" : ""} ${className ?? ""}`.trim()}>
      <div className="cutline" aria-hidden="true">
        <span className="cutline-dash" />
        <span className="micro micro-sm">Cut along the dotted line</span>
        <span className="cutline-dash" />
      </div>
      <div className="coupon" ref={couponRef} role="group" aria-label="Setup coupon">
        <div className="coupon-stub">
          <BucketMark size={compact ? 18 : 24} />
          <span className="micro micro-sm">Coupon</span>
          <span className="coupon-free">{stub}</span>
          <span className="micro micro-sm">{serial}</span>
        </div>
        <div className="coupon-body">
          <span className="micro micro-sm">Good for one setup · paste into any coding agent</span>
          <code className="coupon-cmd">$ {command}</code>
          <div className="coupon-foot">
            <span className="coupon-note">{note}</span>
            <button type="button" className="coupon-tear" onClick={tear}>
              {buttonLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

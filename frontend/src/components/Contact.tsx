import { useCallback, useEffect, useRef, useState } from "react";
import avatar from "../assets/avatar.jpg";
import { copyText } from "./Coupon";
import { Logo } from "./Logo";
import "../styles/contact.css";

export interface ContactProps {
  gravatarUrl: string;
  email: string;
  github: string;
  linkedin: string;
  x: string;
  online: boolean;
}

const COPIED_MS = 1800;
const host = (url: string) => url.replace(/^https?:\/\//, "").replace(/\/$/, "");

export function Contact({ gravatarUrl, email, github, linkedin, x, online }: ContactProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const onCopyEmail = useCallback(() => {
    copyText(email);
    setCopied(true);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), COPIED_MS);
  }, [email]);

  const listings = [
    { label: "The phonebook", sub: "Gravatar", href: gravatarUrl },
    { label: "GitHub", sub: "Code", href: github },
    { label: "LinkedIn", sub: "Work", href: linkedin },
    { label: "X", sub: "Notes", href: x },
  ];

  return (
    <section className="sheet contact" id="contact" data-sec data-folio="Back cover" data-screen-label="Contact">
      <div className="frame">
        {/* NAV */}
        <div className="pagehead">
          <span>Contact</span>
          <span className="ph-mid">Bucket.io directory</span>
          <span>Back cover</span>
        </div>

        {/* PAGE IDENTIFIER -> HEADING -> LEAD */}
        <header className="ct-grid ct-masthead">
          <div className="micro ct-kicker">Back cover · the publisher</div>
          <h2 className="display-lg ct-title" data-reveal>
            Built by Abdullahi Abdi
          </h2>
          <p className="ct-lead">
            Bucket.io is a one-person press. Every listing in this directory was set, checked and printed by a
            student who spends most days thinking like a computer scientist.
          </p>
        </header>

        {/* LARGE IMAGE — newspaper clipping */}
        <div className="ct-grid ct-figure-row">
          <figure className="ct-figure" data-reveal>
            <div className="ct-clip">
              <div className="ct-clip-paper">
                <span className="ct-halftone">
                  <img src={avatar} width={300} height={376} alt="Abdullahi Abdi" />
                </span>
                <figcaption className="ct-caption">
                  <span className="ct-caption-fig">Fig. 1</span>
                  The publisher, photographed in the field.
                </figcaption>
              </div>
            </div>
          </figure>

          {/* BIOGRAPHY */}
          <div className="ct-bio">
            <div className="micro">The publisher</div>
            <p>
              <strong>Abdullahi Abdi</strong> — student, computer scientist.
            </p>
            <p>Built this directory to reduce the hassle of memorizing your reaches.</p>
          </div>
        </div>

        {/* ENQUIRE */}
        <div className="ct-grid ct-enquire">
          <div className="micro ct-kicker">Directory assistance · the phonebook</div>
          <h3 className="ct-h3">Write to the desk</h3>
          <p className="ct-body">
            Have a setup issue, an improvement, or a company format worth adding? I’d like to hear about it.
          </p>
          <div className="ct-actions" data-reveal>
            <button type="button" className="btn btn-verm" onClick={onCopyEmail} aria-live="polite">
              {copied ? "Copied ✓" : "Copy my email"}
            </button>
            <a className="ct-email" href={`mailto:${email}`}>
              {email}
            </a>
          </div>
        </div>

        {/* LISTINGS — dense list */}
        <div className="ct-grid ct-listings">
          <div className="micro ct-kicker">Listings · elsewhere</div>
          <ul className="ct-list">
            {listings.map((listing) => (
              <li key={listing.label}>
                <a href={listing.href} target="_blank" rel="noopener">
                  <span className="ct-list-label">{listing.label}</span>
                  <span className="micro ct-list-sub">{listing.sub}</span>
                  <span className="micro ct-list-host">{host(listing.href)}</span>
                  <span className="ct-list-arrow" aria-hidden="true">
                    ↗
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </div>

        {/* FOOTER */}
        <footer className="ct-colophon">
          <span className="ct-colophon-left">
            <Logo size={20} />
            <span>Not affiliated with Treg. Printed on your own machine.</span>
          </span>
          <span>Set in Montagu Slab, Basteleur &amp; PicNic</span>
        </footer>

        <div className="folio">— Back cover —</div>
        {online ? null : <p className="micro contact-offline">Offline demo — the bucket is not running.</p>}
      </div>
    </section>
  );
}

import type { RefObject } from "react";
import { Logo } from "./Logo";

export interface HeaderProps {
  headerRef: RefObject<HTMLElement | null>;
  folio: string;
  active: string;
  repoUrl: string;
  onNav: (id: string) => void;
}

const NAV = [
  { id: "features", label: "What it does" },
  { id: "white", label: "White pages" },
  { id: "yellow", label: "Yellow pages" },
  { id: "assist", label: "Try it" },
  { id: "docs", label: "Docs" },
  { id: "contact", label: "Contact" },
];

export function Header({ headerRef, folio, active, repoUrl, onNav }: HeaderProps) {
  return (
    <header ref={headerRef} data-header className="site-header">
      <div className="site-header-inner">
        <button
          type="button"
          className="site-header-logo"
          onClick={() => onNav("top")}
          aria-label="BucketIO directory, back to the cover"
        >
          <Logo size={24} />
        </button>
        <span className="site-header-spacer" />
        <nav className="site-header-nav" aria-label="Sections">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={active === item.id ? "is-active" : undefined}
              aria-current={active === item.id ? "true" : undefined}
              onClick={() => onNav(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <span className="site-header-folio micro">{folio}</span>
        <a className="btn-outline site-header-repo" href={repoUrl} target="_blank" rel="noopener">
          GitHub ↗
        </a>
      </div>
    </header>
  );
}

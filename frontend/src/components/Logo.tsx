/* The BucketIO mark: a plain bucket, drawn to sit in ink on paper. */

interface BucketMarkProps {
  size?: number;
  className?: string;
}

export function BucketMark({ size = 26, className }: BucketMarkProps) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <path d="M11.2 3.4h9.6l1.9 5H9.3l1.9-5Z" fill="currentColor" />
      <path
        d="M5.6 8.4h20.8l-1.9 19.1a2.6 2.6 0 0 1-2.6 2.3H10.1a2.6 2.6 0 0 1-2.6-2.3L5.6 8.4Z"
        fill="currentColor"
      />
      <path
        d="M12.6 13.4v12.2M19.4 13.4v12.2"
        stroke="var(--paper-bright)"
        strokeWidth="1.7"
        strokeLinecap="round"
        fill="none"
      />
      <path d="M4.6 8.4h22.8" stroke="currentColor" strokeWidth="2.4" strokeLinecap="square" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="logo-lockup">
      <span className="logo-word">
        Bucket<span className="logo-dot">.</span>io
      </span>
      <span className="logo-sub">Directory</span>
    </span>
  );
}

interface LogoProps {
  size?: number;
  className?: string;
}

export function Logo({ size = 26, className }: LogoProps) {
  return (
    <span className={`logo ${className ?? ""}`.trim()}>
      <BucketMark size={size} />
      <Wordmark />
    </span>
  );
}

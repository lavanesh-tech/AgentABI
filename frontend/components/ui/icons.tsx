/**
 * Hand-authored inline SVG icon set (spec: "avoid unnecessary dependencies" —
 * no icon library exists in package.json, so nav/theme/menu icons are plain
 * components instead of pulling in lucide-react or similar).
 *
 * All icons share a 20x20 viewBox, 1.6px stroke, `currentColor` — they pick
 * up color from Tailwind text-color utilities and resize with font-size /
 * explicit className sizing.
 */

import type { SVGProps } from "react";

export type IconProps = SVGProps<SVGSVGElement>;

function base(props: IconProps) {
  return {
    xmlns: "http://www.w3.org/2000/svg",
    viewBox: "0 0 20 20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    ...props,
  };
}

export function DashboardIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="2.5" y="2.5" width="6.5" height="6.5" rx="1.2" />
      <rect x="11" y="2.5" width="6.5" height="4" rx="1.2" />
      <rect x="11" y="8.5" width="6.5" height="9" rx="1.2" />
      <rect x="2.5" y="11" width="6.5" height="6.5" rx="1.2" />
    </svg>
  );
}

export function ProjectsIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M2.5 5.5a1.5 1.5 0 0 1 1.5-1.5h3.4l1.6 2h7a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 16 16H4a1.5 1.5 0 0 1-1.5-1.5v-9Z" />
    </svg>
  );
}

export function ComponentsIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="3" width="6" height="6" rx="1" />
      <rect x="11" y="3" width="6" height="6" rx="1" />
      <rect x="3" y="11" width="6" height="6" rx="1" />
      <rect x="11" y="11" width="6" height="6" rx="1" />
    </svg>
  );
}

export function CompatibilityIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 10.5 8 14.5 16 5.5" />
    </svg>
  );
}

export function GraphIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="10" cy="4" r="2" />
      <circle cx="4" cy="16" r="2" />
      <circle cx="16" cy="16" r="2" />
      <path d="M10 6v4M10 10l-4.5 4M10 10l4.5 4" />
    </svg>
  );
}

export function TrajectoriesIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 16c2-6 4-3 6-8s4.5-4 8-4" />
      <circle cx="17" cy="4" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function ReplaysIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 10a6 6 0 1 1 1.8 4.3" />
      <path d="M4 14.5V10h4.5" />
    </svg>
  );
}

export function DifferentialIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M6.5 3v11a2 2 0 0 0 2 2H16" />
      <path d="M13.5 13 16 15.5 13.5 18" />
      <path d="M13.5 17H4a2 2 0 0 1-2-2V4" />
      <path d="M6.5 6 4 3.5 6.5 1" />
    </svg>
  );
}

export function RiskIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M10 2.5 17.5 15.5H2.5L10 2.5Z" />
      <path d="M10 8v3.5" />
      <circle cx="10" cy="13.6" r="0.15" fill="currentColor" stroke="currentColor" strokeWidth={1.2} />
    </svg>
  );
}

export function GitHubIcon(props: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden
      {...props}
    >
      <path d="M12 .5C5.73.5.98 5.24.98 11.52c0 5.02 3.26 9.28 7.77 10.78.57.1.78-.25.78-.55 0-.27-.01-1.17-.02-2.12-3.16.69-3.83-1.34-3.83-1.34-.52-1.3-1.26-1.65-1.26-1.65-1.03-.71.08-.69.08-.69 1.14.08 1.74 1.17 1.74 1.17 1.01 1.74 2.65 1.24 3.3.95.1-.73.4-1.24.72-1.53-2.52-.29-5.17-1.26-5.17-5.6 0-1.24.44-2.25 1.17-3.04-.12-.29-.51-1.45.11-3.02 0 0 .96-.31 3.14 1.16.91-.25 1.89-.38 2.86-.39.97 0 1.95.13 2.86.39 2.18-1.47 3.14-1.16 3.14-1.16.62 1.57.23 2.73.11 3.02.73.79 1.17 1.8 1.17 3.04 0 4.35-2.65 5.31-5.18 5.59.41.35.77 1.04.77 2.11 0 1.52-.01 2.75-.01 3.12 0 .3.2.66.79.55A11.03 11.03 0 0 0 23.02 11.5C23.02 5.24 18.27.5 12 .5Z" />
    </svg>
  );
}

export function AuditIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="4" y="2.5" width="12" height="15" rx="1.5" />
      <path d="M7 6.5h6M7 9.5h6M7 12.5h3.5" />
    </svg>
  );
}

export function SunIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="10" cy="10" r="3.2" />
      <path d="M10 2.5v1.6M10 15.9v1.6M17.5 10h-1.6M4.1 10H2.5M15.3 4.7l-1.15 1.15M5.85 14.15 4.7 15.3M15.3 15.3l-1.15-1.15M5.85 5.85 4.7 4.7" />
    </svg>
  );
}

export function MoonIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M16.5 12.3A6.7 6.7 0 0 1 7.7 3.5a6.9 6.9 0 1 0 8.8 8.8Z" />
    </svg>
  );
}

export function SystemThemeIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="2.5" y="3.5" width="15" height="10" rx="1.3" />
      <path d="M7 17h6M10 13.5V17" />
    </svg>
  );
}

export function MenuIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 5.5h14M3 10h14M3 14.5h14" />
    </svg>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 5l10 10M15 5 5 15" />
    </svg>
  );
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 7.5 10 12.5 15 7.5" />
    </svg>
  );
}

export function SignOutIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M8 17H4.5A1.5 1.5 0 0 1 3 15.5v-11A1.5 1.5 0 0 1 4.5 3H8" />
      <path d="M12.5 13.5 17 10l-4.5-3.5M17 10H7.5" />
    </svg>
  );
}

/** Compact AgentABI wordmark — a shield/checkmark glyph (deterministic
 * pass/fail evaluation) plus set type, not a decorative logo. */
export function AgentABIMark(props: IconProps) {
  return (
    <svg {...base({ strokeWidth: 1.7, ...props })}>
      <path d="M10 2 16.5 4.5v5c0 4.2-2.7 6.9-6.5 8.5-3.8-1.6-6.5-4.3-6.5-8.5v-5L10 2Z" />
      <path d="M7 10.2 9.2 12.4 13.3 7.8" />
    </svg>
  );
}

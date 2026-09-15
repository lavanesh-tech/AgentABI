import clsx from "clsx";
import type { ReactNode } from "react";

export function Card({
  children,
  className,
  padded = false,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div
      className={clsx(
        "rounded-lg border border-border bg-surface-raised shadow-sm",
        padded && "p-4",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
      <div className="min-w-0">
        <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

/** Page-level heading used at the top of every route: name, optional
 * one-line description, optional trailing actions. Establishes the
 * typographic hierarchy the spec asks for without every page re-deriving
 * its own heading markup. */
export function PageHeader({
  title,
  description,
  action,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 pb-5">
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-faint">{eyebrow}</p>
        )}
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-ink-muted">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  );
}

/** Small labeled metric block used across Dashboard/Project/Graph/Differential
 * summaries — a single consistent stat presentation instead of each page
 * inventing its own. Purely a display of numbers the caller already has;
 * never fabricates a value itself. */
export function StatTile({
  label,
  value,
  tone = "neutral",
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: "neutral" | "pass" | "warn" | "block" | "accent";
}) {
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2.5">
      <p className="text-xs font-medium text-ink-muted">{label}</p>
      <p
        className={clsx(
          "mt-0.5 text-lg font-semibold tabular-nums",
          tone === "neutral" && "text-ink",
          tone === "pass" && "text-pass",
          tone === "warn" && "text-warn",
          tone === "block" && "text-block",
          tone === "accent" && "text-accent",
        )}
      >
        {value}
      </p>
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  type = "button",
  disabled,
  className,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
  title?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-accent text-white hover:opacity-90",
        variant === "secondary" && "border border-border bg-surface text-ink hover:bg-surface-sunken",
        variant === "ghost" && "text-ink-muted hover:bg-surface-sunken hover:text-ink",
        variant === "danger" && "border border-block/40 text-block hover:bg-block/10",
        className,
      )}
    >
      {children}
    </button>
  );
}

/** Square icon-only button — always requires an aria-label since there is
 * no visible text (spec §14 accessibility). */
export function IconButton({
  children,
  onClick,
  label,
  className,
  active = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  label: string;
  className?: string;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={clsx(
        "flex h-8 w-8 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink",
        active && "bg-surface-sunken text-ink",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "pass" | "warn" | "block" | "accent";
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        tone === "neutral" && "bg-surface-sunken text-ink-muted ring-border",
        tone === "pass" && "bg-pass/10 text-pass ring-pass/30",
        tone === "warn" && "bg-warn/10 text-warn ring-warn/30",
        tone === "block" && "bg-block/10 text-block ring-block/30",
        tone === "accent" && "bg-accent/10 text-accent ring-accent/30",
      )}
    >
      {tone !== "neutral" && (
        <span
          aria-hidden
          className={clsx(
            "h-1.5 w-1.5 rounded-full",
            tone === "pass" && "bg-pass",
            tone === "warn" && "bg-warn",
            tone === "block" && "bg-block",
            tone === "accent" && "bg-accent",
          )}
        />
      )}
      {children}
    </span>
  );
}

export function EmptyState({
  message,
  hint,
  icon,
  action,
}: {
  message: string;
  hint?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon && <div className="mb-1 text-ink-faint">{icon}</div>}
      <p className="text-sm font-medium text-ink-muted">{message}</p>
      {hint && <p className="max-w-sm text-xs text-ink-faint">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, requestId }: { message: string; requestId?: string }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-1 px-6 py-14 text-center"
    >
      <p className="text-sm font-medium text-block">{message}</p>
      {requestId && <p className="text-xs text-ink-faint">Request ID: {requestId}</p>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded bg-surface-sunken", className)} aria-hidden />;
}

export function LoadingBlock() {
  return (
    <div className="space-y-2 p-4" role="status" aria-label="Loading">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
    </div>
  );
}

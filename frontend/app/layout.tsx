import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Providers } from "./providers";
import { THEME_INIT_SCRIPT } from "@/components/ui/ThemeToggle";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentABI — Agent Compatibility & Upgrade Intelligence",
  description: "Know whether an AI-agent change is safe before you ship it.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* Applies a stored light/dark preference before first paint so
            there's no flash of the wrong theme. Defensive: never throws. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

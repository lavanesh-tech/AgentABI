import { describe, expect, it } from "vitest";
import { formatDuration, truncateSha } from "@/lib/format";

describe("format utilities", () => {
  it("truncates a SHA to 7 characters by default", () => {
    expect(truncateSha("abc123def456")).toBe("abc123d");
  });

  it("returns an em dash for a missing SHA", () => {
    expect(truncateSha(null)).toBe("—");
  });

  it("formats sub-second durations in ms and longer ones in seconds", () => {
    expect(formatDuration(450)).toBe("450ms");
    expect(formatDuration(2500)).toBe("2.50s");
    expect(formatDuration(null)).toBe("—");
  });
});

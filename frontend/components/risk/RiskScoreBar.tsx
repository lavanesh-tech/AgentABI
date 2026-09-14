/** Visualizes the configured PASS(0-29)/WARN(30-69)/BLOCK(70-100)
 * thresholds (spec §22). Purely a rendering of `score`/`decision` the
 * backend already computed — never recalculates the decision. */
export function RiskScoreBar({ score, hardBlock }: { score: number; hardBlock: boolean }) {
  const clamped = Math.max(0, Math.min(100, score));
  return (
    <div>
      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-surface-sunken">
        <div className="absolute inset-y-0 left-0 w-[30%] bg-pass/20" />
        <div className="absolute inset-y-0 left-[30%] w-[40%] bg-warn/20" />
        <div className="absolute inset-y-0 left-[70%] w-[30%] bg-block/20" />
        <div
          className="absolute inset-y-0 w-0.5 bg-ink"
          style={{ left: `${clamped}%` }}
          aria-hidden
        />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-ink-faint">
        <span>0 · PASS</span>
        <span>30 · WARN</span>
        <span>70 · BLOCK</span>
        <span>100</span>
      </div>
      {hardBlock && (
        <p className="mt-2 text-xs font-medium text-block">
          BLOCK was forced by a hard-block rule, independent of score.
        </p>
      )}
    </div>
  );
}

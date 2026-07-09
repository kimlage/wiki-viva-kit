export type DockTelemetryTone = "good" | "warn" | "bad" | "info" | "muted";

export type DockTelemetryItem = {
  key: string;
  label: string;
  value: string | number;
  tone: DockTelemetryTone;
  ratio?: number;
  detail?: string;
};

function clampRatio(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(value, 1));
}

export function DockTelemetryRail({ label, items }: { label: string; items: DockTelemetryItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="dockTelemetry" aria-label={label}>
      {items.map((item) => (
        <span className={`dockTelemetryItem dockTelemetryItem-${item.tone}`} title={item.detail || item.label} key={item.key}>
          <span className="dockTelemetryTop">
            <small>{item.label}</small>
            <strong>{item.value}</strong>
          </span>
          <span className="dockTelemetryMeter" aria-hidden>
            <i style={{ width: `${Math.round(clampRatio(item.ratio) * 100)}%` }} />
          </span>
        </span>
      ))}
    </div>
  );
}

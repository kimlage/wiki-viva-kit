import { AlertTriangle, CheckCircle2, KeyRound, LockKeyhole } from "lucide-react";
import { t } from "../data/i18n";
import { useEffect, useState } from "react";
import type { SourceEntity, SourceOperationPreview, SourceAccess } from "../types";

type UpdateRoute = NonNullable<SourceEntity["update_route"]> | NonNullable<SourceOperationPreview["execution"]>;

export function SourceAuthorizationCard({
  source,
  route,
  agentName,
  agentCapabilitiesKnown,
  agentReady,
  connectorReady,
  access,
  probeFailed = false,
  onRevalidate,
  onConfigure,
  compact = false,
  nativeManaged = false,
  revalidateLabel
}: {
  compact?: boolean;
  nativeManaged?: boolean;
  revalidateLabel?: string;
  source: SourceEntity;
  route?: UpdateRoute;
  agentName: string;
  agentCapabilitiesKnown: boolean;
  agentReady: boolean;
  connectorReady: boolean;
  access?: SourceAccess;
  probeFailed?: boolean;
  onRevalidate?: () => void;
  onConfigure?: () => void;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [access]);
  const bound = access?.binding_sha256 === source.access?.binding_sha256;
  const current = bound && access?.valid_until && Number.isFinite(Date.parse(access.valid_until)) && Date.parse(access.valid_until) > now;
  const verified = Boolean(current && access?.verified && access.status === "verified" &&
    access.confirmed_identity === source.access_policy?.expected_identity &&
    source.access_policy?.requested_scopes?.every((scope) => access.granted_scopes.includes(scope)));
  const auth = source.auth;
  const authDeclared = Boolean(auth && auth.method !== "none" && auth.ref);
  const noAuthRequired = auth?.method === "none";
  const connectorBlocked = Boolean(!nativeManaged && route?.requires_agent && agentCapabilitiesKnown && (!agentReady || !connectorReady));
  const connectorAvailable = Boolean(!nativeManaged && route?.requires_agent && agentCapabilitiesKnown && agentReady && connectorReady);
  const status = probeFailed ? "technical_blocked" : access?.valid_until && bound && !current ? "unknown" : access && bound && !["configured", "not_configured"].includes(access.status) && !verified && access.status !== "verified" ? access.status : verified
    ? "verified"
    : connectorBlocked
      ? "blocked"
      : connectorAvailable
        ? "ready"
        : noAuthRequired
          ? "notRequired"
          : authDeclared
            ? "configured"
            : "undeclared";
  const healthy = status === "verified";
  const StatusIcon = healthy ? CheckCircle2 : AlertTriangle;
  const detail = status === "blocked"
    ? t("source.auth.status.blockedDetail", { agent: agentName, connector: route?.mcp_hint || "MCP" })
    : t(`source.auth.status.${status}Detail`, { agent: agentName });

  if (compact) return <span className={`pill pill-${healthy ? "good" : "muted"}`}>
    {t("source.access.connection")}: {t(`source.auth.status.${status}`)}
  </span>;

  return (
    <section className={`sourceAuthorizationCard ${healthy ? "healthy" : status}`} aria-label={t("source.auth.accessTitle")}>
      <header>
        <span className="sourceAuthorizationIcon"><LockKeyhole size={16} aria-hidden /></span>
        <span>
          <small>{t("source.auth.eyebrow")}</small>
          <strong>{t("source.auth.accessTitle")}</strong>
        </span>
        <span className={`pill pill-${healthy ? "good" : status === "blocked" ? "warn" : "muted"}`}>
          {t(`source.auth.status.${status}`)}
        </span>
      </header>
      <dl>
        <dt>{t("source.access.source")}</dt><dd>{source.title} · {source.context}</dd>
        <dt>{t("source.access.coordinator")}</dt><dd>{source.access_policy?.coordinator || t("source.access.unknown")}</dd>
        <dt>{t("source.access.executor")}</dt><dd>{source.access_policy?.executor || t("source.access.unknown")}</dd>
        <dt>{t("source.access.expected")}</dt><dd>{source.access_policy?.expected_identity || t("source.access.unknown")}</dd>
        <dt>{t("source.access.confirmed")}</dt><dd>{bound ? access?.confirmed_identity || t("source.access.unknown") : t("source.access.unknown")}</dd>
        <dt>{t("source.access.requested")}</dt><dd>{source.access_policy?.requested_scopes?.join(", ") || t("source.access.unknown")}</dd>
        <dt>{t("source.access.granted")}</dt><dd>{bound ? access?.granted_scopes.join(", ") || t("source.access.unknown") : t("source.access.unknown")}</dd>
        <dt>{t("source.access.checked")}</dt><dd>{bound ? access?.checked_at || t("source.access.unknown") : t("source.access.unknown")}</dd>
        <dt>{t("source.access.valid")}</dt><dd>{bound ? access?.valid_until || t("source.access.unknown") : t("source.access.unknown")}</dd>
        <dt>{t("source.access.updated")}</dt><dd>{source.updated_at || t("source.access.unknown")}</dd>
        <dt>{t("source.access.error")}</dt><dd>{probeFailed ? "probe_failed" : bound ? access?.error_code || "—" : "—"}</dd>
        <dt>{t("source.auth.method")}</dt>
        <dd>{auth?.method && auth.method !== "none" ? auth.method : t("source.auth.none")}</dd>
        <dt>{t("source.auth.pointer")}</dt>
        <dd>{auth?.ref ? <code>{auth.ref}</code> : t("source.auth.notDeclared")}</dd>
        <dt>{t("source.auth.scopes")}</dt>
        <dd>{auth?.scopes?.length ? auth.scopes.join(", ") : t("source.auth.noScopes")}</dd>
        <dt>{t("source.auth.route")}</dt>
        <dd>{t(`source.refresh.mode.${route?.mode ?? "manual_export"}`)}</dd>
      </dl>
      <p className="sourceAuthorizationStatus">
        <StatusIcon size={14} aria-hidden />
        <span>{detail}</span>
      </p>
      <p className="sourceAuthorizationSafety"><KeyRound size={12} aria-hidden /> {t("source.auth.safety")}</p>
      <p>{t("source.access.boundary")}</p>
      <div className="sourceUpdateActions">
        {onConfigure && <button type="button" className="secondaryButton" onClick={onConfigure}>{t("source.access.configure")}</button>}
        {onRevalidate ? <button type="button" className="secondaryButton" onClick={onRevalidate}>{revalidateLabel || t("source.access.revalidate")}</button> : <p>{t(nativeManaged ? "source.access.nativeControlsBelow" : "source.access.unsupported")}</p>}
      </div>
    </section>
  );
}

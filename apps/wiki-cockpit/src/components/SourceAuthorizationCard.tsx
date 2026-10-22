import { AlertTriangle, CheckCircle2, KeyRound, LockKeyhole } from "lucide-react";
import { t } from "../data/i18n";
import type { SourceEntity, SourceOperationPreview } from "../types";

type UpdateRoute = NonNullable<SourceEntity["update_route"]> | NonNullable<SourceOperationPreview["execution"]>;

export function SourceAuthorizationCard({
  source,
  route,
  agentName,
  agentCapabilitiesKnown,
  agentReady,
  connectorReady,
  liveAccessVerified
}: {
  source: SourceEntity;
  route?: UpdateRoute;
  agentName: string;
  agentCapabilitiesKnown: boolean;
  agentReady: boolean;
  connectorReady: boolean;
  liveAccessVerified: boolean;
}) {
  const auth = source.auth;
  const authDeclared = Boolean(auth && auth.method !== "none" && auth.ref);
  const noAuthRequired = auth?.method === "none";
  const connectorBlocked = Boolean(route?.requires_agent && agentCapabilitiesKnown && (!agentReady || !connectorReady));
  const connectorAvailable = Boolean(route?.requires_agent && agentCapabilitiesKnown && agentReady && connectorReady);
  const status = liveAccessVerified
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
  const healthy = ["verified", "ready", "notRequired"].includes(status);
  const StatusIcon = healthy ? CheckCircle2 : AlertTriangle;
  const detail = status === "blocked"
    ? t("source.auth.status.blockedDetail", { agent: agentName, connector: route?.mcp_hint || "MCP" })
    : t(`source.auth.status.${status}Detail`, { agent: agentName });

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
    </section>
  );
}

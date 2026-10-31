import type { AccessRequirement } from "../data/actionBoard";
import { uiLanguage } from "../data/i18n";

export function ActionAccessRequirements({ requirements, actionId }: { requirements?: AccessRequirement[]; actionId: string }) {
  const language = uiLanguage();
  const copy = language === "pt" ? { action: "Requisito desta ação", profile: "Requisito do perfil", identity: "Identidade esperada", effective: "Identidade efetiva e acesso atual: não verificados", recovery: "Recuperação" }
    : language === "es" ? { action: "Requisito de esta acción", profile: "Requisito del perfil", identity: "Identidad esperada", effective: "Identidad efectiva y acceso actual: no verificados", recovery: "Recuperación" }
    : { action: "Requirement for this action", profile: "Profile requirement", identity: "Expected identity", effective: "Effective identity and current access: not verified", recovery: "Recovery" };
  return <>{requirements?.filter(row => !row.action_ids || row.action_ids.includes(actionId)).map((row, index) => <details key={`${row.service}-${index}`}>
    <summary>{row.action_ids ? copy.action : copy.profile} · {row.service}{row.operation ? ` · ${row.operation}` : ""}</summary>
    <p>{copy.identity}: {row.expected_identity}</p>{row.resource && <p>{row.resource}</p>}<p>{row.method}</p>
    <p>{copy.effective}</p>{row.recovery && <p>{copy.recovery}: {row.recovery}</p>}
  </details>)}</>;
}

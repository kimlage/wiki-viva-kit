import { t } from "../data/i18n";
import type { InformationUse } from "../types";
import { useEffect, useState } from "react";

function explanation(reason: string): string {
  if (/expired|future|not_yet_valid|no_longer_valid/.test(reason)) return t("information.reason.validity");
  if (reason === "information_changed_since_verification") return t("information.reason.changed");
  if (/missing|unreadable/.test(reason)) return t("information.reason.missing");
  return t("information.reason.unconfirmed");
}

/** Reading is passive. Execution validates the declared information use again. */
export function InformationNotice({ frontmatter, assessment }: { frontmatter: Record<string, unknown>; assessment?: InformationUse }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => setNow(Date.now()), [assessment]);
  useEffect(() => {
    const current = Date.now();
    const deadlines = assessment?.requirements.filter(row => row.temporal === "current" && row.valid_until)
      .map(row => Date.parse(row.valid_until!)).filter(deadline => deadline >= current) ?? [];
    if (deadlines.length === 0) return;
    const timer = window.setTimeout(() => setNow(Date.now()), Math.min(Math.min(...deadlines) - current + 1, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [assessment, now]);
  const verifiedAt = typeof frontmatter.verified_at === "string" ? frontmatter.verified_at : "";
  const requirements = Array.isArray(frontmatter.information_requirements)
    ? frontmatter.information_requirements.filter((value): value is Record<string, unknown> =>
      Boolean(value) && typeof value === "object" && !Array.isArray(value)) : [];
  if (!verifiedAt && requirements.length === 0 && !assessment) return null;
  const expired = assessment?.requirements.some(row => row.temporal === "current" && row.valid_until && now > Date.parse(row.valid_until));
  const blocked = assessment && (!assessment.ready || expired);
  return <aside className="readerInformationNotice" aria-label={t("information.title")}>
    <strong>{t("information.title")}</strong>
    {(verifiedAt || !assessment) && <p>{verifiedAt ? t("information.verified", { when: verifiedAt }) : t("information.noVerification")}</p>}
    {assessment && <>
      <p>{t(blocked ? "information.blocked" : "information.assessed")}</p>
      <p>{t("information.assessedAt", { when: assessment.assessed_at })}</p>
      {assessment.relation_errors.length > 0 && <p>{t("information.reason.missing")}</p>}
      <ul>{assessment.requirements.map((row, index) => <li key={index}>
        <span>{row.target} · {row.fields.join(", ")}</span>
        <p>{t(row.temporal === "historical" ? "information.historical" : "information.current")}</p>
        <p>{row.verified_at ? t("information.verified", { when: row.verified_at }) : t("information.noVerification")}</p>
        {[...new Set(row.blockers.map(explanation))].map(reason => <p key={reason}>{reason}</p>)}
      </li>)}</ul>
    </>}
    {!assessment && requirements.length > 0 && <ul>{requirements.map((requirement, index) => <li key={index}>
      <span>{String(requirement.target || t("information.unknownTarget"))}</span>
      {Array.isArray(requirement.fields) && <span> · {requirement.fields.filter(v => typeof v === "string").join(", ")}</span>}
      <p>{t(requirement.temporal === "historical" ? "information.historical" : "information.current")}</p>
    </li>)}</ul>}
  </aside>;
}

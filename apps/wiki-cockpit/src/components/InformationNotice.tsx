import { t } from "../data/i18n";

/** Reading is passive. Execution validates the declared information use again. */
export function InformationNotice({ frontmatter }: { frontmatter: Record<string, unknown> }) {
  const verifiedAt = typeof frontmatter.verified_at === "string" ? frontmatter.verified_at : "";
  const requirements = Array.isArray(frontmatter.information_requirements)
    ? frontmatter.information_requirements.filter((value): value is Record<string, unknown> =>
      Boolean(value) && typeof value === "object" && !Array.isArray(value)) : [];
  if (!verifiedAt && requirements.length === 0) return null;
  return <aside className="readerInformationNotice" aria-label={t("information.title")}>
    <strong>{t("information.title")}</strong>
    <p>{verifiedAt ? t("information.verified", { when: verifiedAt }) : t("information.noVerification")}</p>
    {requirements.length > 0 && <ul>{requirements.map((requirement, index) => <li key={index}>
      <span>{String(requirement.target || t("information.unknownTarget"))}</span>
      {Array.isArray(requirement.fields) && <span> · {requirement.fields.filter(v => typeof v === "string").join(", ")}</span>}
      <p>{t(requirement.temporal === "historical" ? "information.historical" : "information.current")}</p>
    </li>)}</ul>}
  </aside>;
}

// The founding rite's 2D twin: same 3+1 root-type choice, same single
// question, as a centered card — fallback mode (reduced motion / no WebGL /
// visual tests) has no canvas to host the spatial founding cards.

import { useState } from "react";
import { t } from "../../data/i18n";

export function FoundingFallback({
  demo,
  skipHref,
  onFound
}: {
  demo: boolean;
  skipHref?: string;
  onFound: (rootType: string, name: string) => void;
}) {
  const [rootType, setRootType] = useState("");
  const [others, setOthers] = useState(false);
  const [name, setName] = useState("");
  const options = others ? ["project", "community", "product"] : ["person", "team", "company"];
  return (
    <div className="genesisVoid" role="dialog" aria-label={t("genesis.stage0.title")}>
      <div className="genesisVoidCard">
        {demo && <span className="genesisSim">{t("genesis.sim")}</span>}
        <h1>{t("genesis.stage0.title")}</h1>
        {!rootType ? (
          <>
            <div className="foundingFallbackCards">
              {options.map((option) => (
                <button className="foundingFallbackCard" key={option} onClick={() => setRootType(option)} tabIndex={0} type="button">
                  <strong>{t(`genesis.founding.type.${option}`)}</strong>
                  <small>{t(`genesis.founding.desc.${option}`)}</small>
                </button>
              ))}
            </div>
            <button className="genesisGhost" onClick={() => setOthers((value) => !value)} tabIndex={0} type="button">
              {others ? t("genesis.back") : t("genesis.founding.other")}
            </button>
          </>
        ) : (
          <>
            <label className="intakeField">
              <span>{t(`genesis.founding.prompt.${rootType}`)}</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t(`genesis.founding.eg.${rootType}`)}
                autoFocus
                tabIndex={0}
              />
            </label>
            <p>{demo ? t("genesis.founding.note") : t("genesis.founding.noteReal")}</p>
            <div className="genesisActions">
              <button className="genesisGhost" onClick={() => setRootType("")} tabIndex={0} type="button">
                {t("genesis.back")}
              </button>
              <button
                className="genesisCta"
                disabled={!name.trim()}
                onClick={() => onFound(rootType, name.trim())}
                tabIndex={0}
                type="button"
              >
                {t("genesis.founding.confirm")}
              </button>
            </div>
          </>
        )}
        {skipHref && (
          <a className="genesisSkip" href={skipHref} tabIndex={0}>
            {t("genesis.skip")}
          </a>
        )}
      </div>
    </div>
  );
}

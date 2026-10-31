import { uiLanguage } from "../data/i18n";

export function PreparatoryObservations({ observations, dryRun = false }: { observations?: string[]; dryRun?: boolean }) {
  if (!observations?.length) return null;
  const language = uiLanguage();
  const copy = language === "pt" ? { title: "Observações preparatórias já realizadas", limit: "A simulação limita a execução futura. As consultas preparatórias acima já ocorreram e podem ter reconciliado entradas no serviço." }
    : language === "es" ? { title: "Observaciones preparatorias ya realizadas", limit: "La simulación limita la ejecución futura. Las consultas preparatorias anteriores ya ocurrieron y pueden haber reconciliado entradas en el servicio." }
    : { title: "Preparatory observations already performed", limit: "Dry run limits future execution. The preparatory queries above already occurred and may have reconciled inputs in the service." };
  return <section aria-label={copy.title}><h4>{copy.title}</h4><ul>{observations.map((value, index) => <li key={index}>{value}</li>)}</ul>{dryRun && <p>{copy.limit}</p>}</section>;
}

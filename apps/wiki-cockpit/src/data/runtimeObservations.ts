export type RuntimeObservations = {
  ok: boolean; schema_version: "wiki_runtime_observations.v1"; observed_at: string;
  operator: {
    started_at: string; boot_source_commit: string | null; current_source_commit: string | null;
    content_source_commit: string | null;
    boot_code_sha256?: string | null; current_code_sha256?: string | null;
    restart_required: boolean | null; server_version: string;
    frontend: { status: "not_served" | "observed" | "unavailable"; entry_sha256: string | null; source_commit: null };
  };
};
export type RuntimeObservationReader = (options?: { signal?: AbortSignal }) => Promise<RuntimeObservations>;

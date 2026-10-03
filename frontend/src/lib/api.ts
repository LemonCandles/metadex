export type Cohort = "all" | "high_skill_public_v1";
export type HeroOrder = "picks" | "wins" | "losses" | "pick_rate" | "win_rate";

export type Filters = {
  cohort: Cohort;
  game_mode: number | null;
  lobby_type: number | null;
  skill_min: number | null;
  skill_max: number | null;
  rank_coverage_min: number | null;
};

export type Period = { start: string; end: string; timezone: "UTC"; end_exclusive: true };
export type Sample = {
  matches: number;
  participants: number;
  observed_days: number;
  expected_days: number;
  min_sample_size: number;
};
export type Metadata = {
  period: Period;
  filters: Filters;
  updated_at: string;
  version_id: string;
  sample: Sample;
};
export type HeroMetrics = {
  hero_id: number;
  picks: number;
  wins: number;
  losses: number;
  pick_rate: number | null;
  win_rate: number | null;
  sample_size: number;
  meets_min_sample: boolean;
};
export type Ranking = Metadata & {
  status: "ok" | "no_data" | "below_min_sample";
  ordering: { order_by: HeroOrder; order: "asc" | "desc"; tie_breaker: "hero_id_asc" };
  include_below_min: boolean;
  heroes: HeroMetrics[];
};
export type Detail = Metadata & { status: "ok" | "no_data"; hero: HeroMetrics };
export type TrendPoint = HeroMetrics & { date: string; matches: number; has_data: boolean };
export type Trend = Metadata & {
  hero: HeroMetrics;
  points: TrendPoint[];
  comparison: {
    status: "comparable" | "insufficient_history" | "incomplete_current_period" | "no_current_data";
    period: Period;
    sample: Sample;
    hero: HeroMetrics;
    pick_rate_delta: number | null;
    win_rate_delta: number | null;
  };
};
export type Context = { hero_id: number | null; position: number | null; ally_ids: number[]; opponent_ids: number[] };
export type Suggestion = {
  hero_id: number;
  item_key: string | null;
  sample_size: number;
  wins: number;
  losses: number;
  win_rate: number;
  meets_min_sample: true;
  context_sample_size: number;
  context: Context;
  explanation: string;
  mean_duration_seconds: number;
  mean_purchase_time_seconds: number | null;
  mean_purchase_index: number | null;
};
export type Recommendation = Metadata & {
  status: "ok" | "no_data" | "insufficient_evidence" | "unsupported_context";
  requested_context: Context;
  used_context: Context;
  supported_contexts: { position: boolean; allies: true; opponents: true; hero: boolean };
  item_timing: {
    duration_min_seconds: number | null;
    duration_max_seconds: number | null;
    purchase_time_min_seconds: number | null;
    purchase_time_max_seconds: number;
    purchase_index_min: number | null;
    purchase_index_max: number | null;
  } | null;
  ordering: { order_by: "win_rate_desc"; tie_breakers: string[] };
  fallback: {
    allowed: boolean;
    applied: boolean;
    removed_filters: ("ally_ids" | "opponent_ids")[];
    attempts: { level: "exact" | "without_allies" | "without_draft"; context: Context; context_sample_size: number; candidate_count: number; eligible_count: number }[];
  };
  limitations: string[];
  explanation: string;
  recommendations: Suggestion[];
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const base = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export async function getApi<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { signal, headers: { Accept: "application/json" }, cache: "no-store" });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(0, "Não foi possível conectar à API. Verifique se o backend está em execução.");
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const message = typeof body === "object" && body !== null && "error" in body &&
      typeof body.error === "object" && body.error !== null && "message" in body.error &&
      typeof body.error.message === "string" ? body.error.message : `Erro HTTP ${response.status}`;
    const translated: Record<number, string> = {
      404: "Herói não encontrado na publicação.",
      422: "Parâmetros inválidos. Revise o período e os filtros informados.",
      503: "Os dados publicados estão temporariamente indisponíveis. Tente novamente após a atualização.",
    };
    throw new ApiError(response.status, translated[response.status] || message);
  }
  return response.json() as Promise<T>;
}

export const integer = new Intl.NumberFormat("pt-BR");
export const percent = (value: number | null) => value === null ? "—" : `${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 }).format(value * 100)}%`;
export const signedPercent = (value: number | null) => value === null ? "—" : `${value > 0 ? "+" : ""}${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 }).format(value * 100)} p.p.`;
export const utcDate = (value: string) => new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC", day: "2-digit", month: "short", year: "numeric" }).format(new Date(`${value}T12:00:00Z`));
export const utcDateTime = (value: string) => new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC", dateStyle: "short", timeStyle: "short" }).format(new Date(value));

export function isStale(updatedAt: string): boolean {
  const age = Date.now() - new Date(updatedAt).getTime();
  return Number.isFinite(age) && age > 48 * 60 * 60 * 1000;
}

export type FilterInput = { period_start: string; period_end: string; cohort: Cohort; skill_min: string; skill_max: string; rank_coverage_min: string };
export const emptyFilters: FilterInput = { period_start: "", period_end: "", cohort: "all", skill_min: "", skill_max: "", rank_coverage_min: "" };
export function filtersFromQuery(query: URLSearchParams): FilterInput {
  return {
    period_start: query.get("period_start") || "", period_end: query.get("period_end") || "",
    cohort: query.get("cohort") === "high_skill_public_v1" ? "high_skill_public_v1" : "all",
    skill_min: query.get("skill_min") || "", skill_max: query.get("skill_max") || "",
    rank_coverage_min: query.get("rank_coverage_min") || "",
  };
}
export function appendFilters(query: URLSearchParams, filters: FilterInput) {
  for (const key of ["period_start", "period_end", "skill_min", "skill_max", "rank_coverage_min"] as const) {
    if (filters[key]) query.set(key, filters[key]);
  }
  query.set("cohort", filters.cohort);
  return query;
}
export function validateFilters(filters: FilterInput): string | null {
  if (Boolean(filters.period_start) !== Boolean(filters.period_end)) return "Informe as duas datas do período.";
  if (filters.period_start && filters.period_end) {
    const days = (Date.parse(filters.period_end) - Date.parse(filters.period_start)) / 86400000;
    if (!Number.isFinite(days) || days < 1 || days > 365) return "O período precisa ter de 1 a 365 dias; o fim é exclusivo.";
  }
  if (filters.skill_min && filters.skill_max && Number(filters.skill_min) > Number(filters.skill_max)) return "A habilidade mínima não pode superar a máxima.";
  return null;
}

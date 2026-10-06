"use client";

import Link from "next/link";
import { useState } from "react";
import { appendFilters, emptyFilters, FilterInput, Filters, heroName, integer, isStale, Metadata, percent, rankLabel, rankOptions, utcDate, utcDateTime, validateFilters } from "@/lib/api";
import { useHeroNames } from "@/components/hero-catalog";

function RankSelect({ value, maximum = false, onChange }: { value: string; maximum?: boolean; onChange: (value: string) => void }) {
  const options = rankOptions.map((option) => maximum && option.value === "80" ? { value: "85", label: "Immortal (todos)" } : option);
  return <select value={value} onChange={(event) => onChange(event.target.value)}><option value="">Sem limite</option>{value && !options.some((option) => option.value === value) && <option value={value}>{rankLabel(Number(value))}</option>}{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>;
}

export function FilterBar({ initial = emptyFilters, onApply, title = "Filtrar partidas" }: { initial?: FilterInput; onApply: (filters: FilterInput) => void; title?: string }) {
  const [draft, setDraft] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  function update(key: keyof FilterInput, value: string) { setDraft((previous) => ({ ...previous, [key]: value })); }
  return <form className="filter-panel" onSubmit={(event) => { event.preventDefault(); const message = validateFilters(draft); setError(message); if (!message) onApply(draft); }}>
    <div className="section-heading"><div><p className="eyebrow">Consulta</p><h2>{title}</h2></div><p className="subtle">Datas em UTC · fim exclusivo</p></div>
    <div className="filter-grid">
      <label>Primeiro dia <input type="date" value={draft.period_start} onChange={(event) => update("period_start", event.target.value)} /></label>
      <label>Até antes de <input type="date" value={draft.period_end} onChange={(event) => update("period_end", event.target.value)} /><small>Este dia não entra na análise.</small></label>
      <label>Partidas analisadas <select value={draft.cohort} onChange={(event) => update("cohort", event.target.value)}><option value="all">Todas as partidas coletadas</option><option value="high_skill_public_v1">Divine / Immortal · alto nível</option></select><small>Alto nível: média ≥ Divine, pelo menos 5 ranks e modos balanceados.</small></label>
      <label>Rank médio mínimo <RankSelect value={draft.skill_min} onChange={(value) => update("skill_min", value)} /><small>Média dos ranks informados na partida; não é MMR.</small></label>
      <label>Rank médio máximo <RankSelect maximum value={draft.skill_max} onChange={(value) => update("skill_max", value)} /><small>Não exige que todos os jogadores tenham essa medalha.</small></label>
      <label>Mínimo de jogadores com rank <input type="number" min="1" max="10" step="1" placeholder="Opcional" value={draft.rank_coverage_min} onChange={(event) => update("rank_coverage_min", event.target.value)} /></label>
    </div>
    <div className="filter-actions"><button className="button primary" type="submit">Aplicar filtros</button><button className="button ghost" type="button" onClick={() => { setDraft(emptyFilters); setError(null); onApply(emptyFilters); }}>Limpar</button><span className="subtle">Sem datas: janela padrão de dias completos em UTC.</span></div>
    {error && <p className="form-error" role="alert">{error}</p>}
  </form>;
}

function describeFilters(filters: Filters): string {
  const parts = [filters.cohort === "all" ? "Todas as partidas coletadas" : "Divine / Immortal · alto nível"];
  if (filters.skill_min !== null && filters.skill_max !== null) parts.push(`rank médio de ${rankLabel(filters.skill_min)} até ${rankLabel(filters.skill_max)}`);
  else if (filters.skill_min !== null) parts.push(`rank médio a partir de ${rankLabel(filters.skill_min)}`);
  else if (filters.skill_max !== null) parts.push(`rank médio até ${rankLabel(filters.skill_max)}`);
  if (filters.rank_coverage_min !== null) parts.push(`pelo menos ${filters.rank_coverage_min} jogadores com rank`);
  if (filters.game_mode !== null) parts.push(`modo ${filters.game_mode}`);
  if (filters.lobby_type !== null) parts.push(`lobby ${filters.lobby_type}`);
  return parts.join(" · ");
}

export function DataContext({ data, sampleUnit = "picks" }: { data: Metadata; sampleUnit?: "picks" | "purchases" }) {
  return <section className="context-panel" aria-label="Contexto dos dados">
    <div><span className="context-label">Período analisado</span><strong>{utcDate(data.period.start)} — {utcDate(data.period.end)}</strong><small>UTC · fim exclusivo</small></div>
    <div><span className="context-label">Filtros aplicados</span><strong>{describeFilters(data.filters)}</strong><small>{integer.format(data.sample.observed_days)} de {integer.format(data.sample.expected_days)} dias com partidas</small></div>
    <div><span className="context-label">Amostra de partidas</span><strong>{integer.format(data.sample.matches)} partidas</strong><small>{integer.format(data.sample.participants)} participações de heróis · mínimo {integer.format(data.sample.min_sample_size)} {sampleUnit === "purchases" ? "compradores por item" : "picks por herói"}</small></div>
    <div><span className="context-label">Última atualização</span><strong>{utcDateTime(data.updated_at)} UTC</strong><small>Dados da OpenDota publicados localmente</small></div>
    {isStale(data.updated_at) && <p className="stale-note" role="status">Dados possivelmente desatualizados: a última publicação tem mais de 48 horas. Confirme a rotina de atualização antes de tomar decisões.</p>}
  </section>;
}

export function ResourceState({ loading, error, empty, onRetry, emptyMessage }: { loading: boolean; error: string | null; empty?: boolean; onRetry?: () => void; emptyMessage?: string }) {
  if (loading) return <div className="state-panel" role="status"><span className="spinner" aria-hidden="true" /><h2>Carregando estatísticas</h2><p>Buscando partidas, heróis e resultados.</p></div>;
  if (error) return <div className="state-panel" role="alert"><span className="state-symbol">!</span><h2>Não foi possível carregar</h2><p>{error}</p>{onRetry && <button className="button primary" onClick={onRetry}>Tentar novamente</button>}</div>;
  if (empty) return <div className="state-panel" role="status"><span className="state-symbol">∅</span><h2>Sem resultados com estes filtros</h2><p>{emptyMessage || "Amplie o período ou ajuste os filtros para procurar mais partidas."}</p></div>;
  return null;
}

export function MetricCard({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

export function EvidenceNote() {
  return <p className="evidence-note">Pick rate = partidas com o herói ÷ partidas analisadas. Win rate = vitórias do herói ÷ picks. A coleta cobre parte das partidas e não separa patches; períodos longos podem misturar versões do jogo. Amostras pequenas reduzem a confiança.</p>;
}

export function HeroLink({ id, query = "" }: { id: number; query?: string }) {
  const names = useHeroNames();
  return <Link className="hero-link" href={`/heroes/${id}${query ? `?${query}` : ""}`}>{heroName(names, id)}<span aria-hidden="true">↗</span></Link>;
}

export function queryFor(filters: FilterInput) { return appendFilters(new URLSearchParams(), filters).toString(); }
export function rateLabel(value: number | null) { return percent(value); }

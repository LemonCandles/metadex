"use client";

import Link from "next/link";
import { useState } from "react";
import { appendFilters, emptyFilters, FilterInput, Filters, integer, isStale, Metadata, percent, utcDate, utcDateTime, validateFilters } from "@/lib/api";

export function FilterBar({ initial = emptyFilters, onApply, title = "Ajustar recorte" }: { initial?: FilterInput; onApply: (filters: FilterInput) => void; title?: string }) {
  const [draft, setDraft] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  function update(key: keyof FilterInput, value: string) { setDraft((previous) => ({ ...previous, [key]: value })); }
  return <form className="filter-panel" onSubmit={(event) => { event.preventDefault(); const message = validateFilters(draft); setError(message); if (!message) onApply(draft); }}>
    <div className="section-heading"><div><p className="eyebrow">Consulta</p><h2>{title}</h2></div><p className="subtle">Datas em UTC · fim exclusivo</p></div>
    <div className="filter-grid">
      <label>Início <input type="date" value={draft.period_start} onChange={(event) => update("period_start", event.target.value)} /></label>
      <label>Fim <input type="date" value={draft.period_end} onChange={(event) => update("period_end", event.target.value)} /></label>
      <label>Recorte <select value={draft.cohort} onChange={(event) => update("cohort", event.target.value)}><option value="all">Todas as partidas válidas</option><option value="high_skill_public_v1">Alto nível público</option></select></label>
      <label>Habilidade mín. <input type="number" min="0" max="85" step="0.1" placeholder="Opcional" value={draft.skill_min} onChange={(event) => update("skill_min", event.target.value)} /></label>
      <label>Habilidade máx. <input type="number" min="0" max="85" step="0.1" placeholder="Opcional" value={draft.skill_max} onChange={(event) => update("skill_max", event.target.value)} /></label>
      <label>Ranks informados mín. <input type="number" min="1" max="10" step="1" placeholder="Opcional" value={draft.rank_coverage_min} onChange={(event) => update("rank_coverage_min", event.target.value)} /></label>
    </div>
    <div className="filter-actions"><button className="button primary" type="submit">Aplicar filtros</button><button className="button ghost" type="button" onClick={() => { setDraft(emptyFilters); setError(null); onApply(emptyFilters); }}>Limpar</button><span className="subtle">Sem datas: janela padrão da API.</span></div>
    {error && <p className="form-error" role="alert">{error}</p>}
  </form>;
}

function describeFilters(filters: Filters): string {
  const parts = [filters.cohort === "all" ? "Todas as partidas válidas" : "Alto nível público"];
  if (filters.skill_min !== null && filters.skill_max !== null) parts.push(`habilidade ${filters.skill_min}–${filters.skill_max}`);
  else if (filters.skill_min !== null) parts.push(`habilidade ≥ ${filters.skill_min}`);
  else if (filters.skill_max !== null) parts.push(`habilidade ≤ ${filters.skill_max}`);
  if (filters.rank_coverage_min !== null) parts.push(`ranks informados ≥ ${filters.rank_coverage_min}`);
  if (filters.game_mode !== null) parts.push(`modo ${filters.game_mode}`);
  if (filters.lobby_type !== null) parts.push(`lobby ${filters.lobby_type}`);
  return parts.join(" · ");
}

export function DataContext({ data }: { data: Metadata }) {
  return <section className="context-panel" aria-label="Contexto dos dados">
    <div><span className="context-label">Período analisado</span><strong>{utcDate(data.period.start)} — {utcDate(data.period.end)}</strong><small>UTC · fim exclusivo</small></div>
    <div><span className="context-label">Recorte aplicado</span><strong>{describeFilters(data.filters)}</strong><small>{integer.format(data.sample.observed_days)} de {integer.format(data.sample.expected_days)} dias com partidas</small></div>
    <div><span className="context-label">Amostra geral</span><strong>{integer.format(data.sample.matches)} partidas</strong><small>{integer.format(data.sample.participants)} participações · mínimo {integer.format(data.sample.min_sample_size)} escolhas</small></div>
    <div><span className="context-label">Publicação</span><strong>{utcDateTime(data.updated_at)} UTC</strong><small title={data.version_id}>Versão {data.version_id.slice(0, 12)}</small></div>
    {isStale(data.updated_at) && <p className="stale-note" role="status">Dados possivelmente desatualizados: a última publicação tem mais de 48 horas. Confirme a rotina de atualização antes de tomar decisões.</p>}
  </section>;
}

export function ResourceState({ loading, error, empty, onRetry, emptyMessage }: { loading: boolean; error: string | null; empty?: boolean; onRetry?: () => void; emptyMessage?: string }) {
  if (loading) return <div className="state-panel" role="status"><span className="spinner" aria-hidden="true" /><h2>Carregando dados</h2><p>Consultando a última publicação da API.</p></div>;
  if (error) return <div className="state-panel" role="alert"><span className="state-symbol">!</span><h2>Não foi possível carregar</h2><p>{error}</p>{onRetry && <button className="button primary" onClick={onRetry}>Tentar novamente</button>}</div>;
  if (empty) return <div className="state-panel" role="status"><span className="state-symbol">∅</span><h2>Sem resultados para este recorte</h2><p>{emptyMessage || "Amplie o período ou ajuste os filtros para procurar mais observações."}</p></div>;
  return null;
}

export function MetricCard({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="metric-card"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

export function EvidenceNote() {
  return <p className="evidence-note">Taxa de escolha = escolhas ÷ partidas elegíveis. Taxa de vitória = vitórias ÷ escolhas. Amostras pequenas e cobertura parcial reduzem a confiança; associação observada não demonstra causa.</p>;
}

export function HeroLink({ id, query = "" }: { id: number; query?: string }) {
  return <Link className="hero-link" href={`/heroes/${id}${query ? `?${query}` : ""}`}>Herói #{id}<span aria-hidden="true">↗</span></Link>;
}

export function queryFor(filters: FilterInput) { return appendFilters(new URLSearchParams(), filters).toString(); }
export function rateLabel(value: number | null) { return percent(value); }

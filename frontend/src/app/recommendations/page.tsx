"use client";

import Link from "next/link";
import { useState } from "react";
import { appendFilters, emptyFilters, FilterInput, integer, percent, Recommendation } from "@/lib/api";
import { DataContext, FilterBar, HeroLink, ResourceState, queryFor } from "@/components/ui";
import { useResource } from "@/components/use-resource";

type Mode = "heroes" | "items";
type Draft = { heroId: string; position: string; allies: string; opponents: string; fallback: boolean; limit: string; purchaseMax: string; durationMin: string; durationMax: string };
const initialDraft: Draft = { heroId: "", position: "", allies: "", opponents: "", fallback: true, limit: "10", purchaseMax: "1200", durationMin: "", durationMax: "" };
const levelText = { exact: "Contexto exato", without_allies: "Sem aliados", without_draft: "Sem draft" };
const statusTitle: Record<Recommendation["status"], string> = { ok: "Sugestões com amostra suficiente", no_data: "Sem partidas neste recorte", insufficient_evidence: "Evidência insuficiente", unsupported_context: "Contexto sem suporte" };

function parseIds(raw: string, max: number, label: string): number[] {
  if (!raw.trim()) return [];
  const values = raw.split(/[\s,;]+/).filter(Boolean).map(Number);
  if (values.length > max || values.some((id) => !Number.isInteger(id) || id < 1 || id > 2147483647) || new Set(values).size !== values.length) throw new Error(`${label}: informe até ${max} IDs positivos, distintos e separados por vírgula.`);
  return values;
}
function describeContext(context: Recommendation["requested_context"]) {
  return [context.hero_id && `herói #${context.hero_id}`, context.position && `posição ${context.position}`, context.ally_ids.length && `aliados ${context.ally_ids.map((id) => `#${id}`).join(", ")}`, context.opponent_ids.length && `adversários ${context.opponent_ids.map((id) => `#${id}`).join(", ")}`].filter(Boolean).join(" · ") || "Sem filtros de draft";
}

function RecommendationResults({ path, mode, filters }: { path: string; mode: Mode; filters: FilterInput }) {
  const { data, loading, error, reload } = useResource<Recommendation>(path);
  return <section className="recommendation-results" aria-live="polite"><ResourceState loading={loading} error={error} onRetry={reload} />
    {data && <><DataContext data={data} /><div className="explanation-panel"><p className="eyebrow">Como o ranking foi formado</p><h2>{data.status === "ok" ? `${integer.format(data.recommendations.length)} ${data.recommendations.length === 1 ? "sugestão" : "sugestões"} com amostra suficiente` : statusTitle[data.status]}</h2><p>{data.explanation}</p><div className="context-pair"><div><span>Contexto solicitado</span><strong>{describeContext(data.requested_context)}</strong></div><div><span>Contexto usado</span><strong>{describeContext(data.used_context)}</strong></div></div>{data.fallback.applied && <p className="caution">O recuo removeu {data.fallback.removed_filters.map((key) => key === "ally_ids" ? "aliados" : "adversários").join(" e ")}. Período, recorte e demais filtros permaneceram.</p>}{!data.supported_contexts.position && <p className="subtle">Esta publicação não sustenta filtro por posição econômica conhecida.</p>}{data.item_timing && <p className="subtle">Itens: primeira compra registrada até {integer.format(data.item_timing.purchase_time_max_seconds)} s. Duração: {data.item_timing.duration_min_seconds === null ? "sem limite mínimo" : `mínimo ${integer.format(data.item_timing.duration_min_seconds)} s`}; {data.item_timing.duration_max_seconds === null ? "sem limite máximo" : `máximo ${integer.format(data.item_timing.duration_max_seconds)} s`}.</p>}</div>
      {data.status !== "ok" ? <ResourceState loading={false} error={null} empty emptyMessage={data.explanation} /> : <div className="suggestion-grid">{data.recommendations.map((suggestion, index) => <article className="suggestion-card" key={`${suggestion.hero_id}-${suggestion.item_key || "hero"}`}><div className="suggestion-top"><span className="rank-number">{String(index + 1).padStart(2, "0")}</span><span className="sample-tag">{integer.format(suggestion.sample_size)} observações</span></div><h3>{mode === "heroes" ? <HeroLink id={suggestion.hero_id} query={queryFor(filters)} /> : <><span className="item-key">{suggestion.item_key}</span><small>Herói #{suggestion.hero_id}</small></>}</h3><div className="suggestion-rate"><strong>{percent(suggestion.win_rate)}</strong><span>vitórias observadas</span></div><p>{suggestion.explanation}</p><dl><div><dt>Vitórias / derrotas</dt><dd>{integer.format(suggestion.wins)} / {integer.format(suggestion.losses)}</dd></div><div><dt>Amostra no contexto</dt><dd>{integer.format(suggestion.context_sample_size)}</dd></div><div><dt>Duração média</dt><dd>{Math.round(suggestion.mean_duration_seconds / 60)} min</dd></div>{suggestion.mean_purchase_time_seconds !== null && <div><dt>Compra média</dt><dd>{Math.round(suggestion.mean_purchase_time_seconds / 60)} min · índice {suggestion.mean_purchase_index?.toFixed(1) ?? "—"}</dd></div>}</dl></article>)}</div>}
      <div className="limitations-panel"><h3>Limites desta evidência</h3><ul>{data.limitations.map((item) => <li key={item}>{item}</li>)}</ul><details><summary>Ver tentativas de contexto</summary><ol>{data.fallback.attempts.map((attempt) => <li key={attempt.level}>{levelText[attempt.level]}: {integer.format(attempt.context_sample_size)} participações no contexto, {integer.format(attempt.candidate_count)} candidatos, {integer.format(attempt.eligible_count)} com amostra mínima.</li>)}</ol></details></div>
    </>}
  </section>;
}

export default function RecommendationsPage() {
  const [mode, setMode] = useState<Mode>("heroes");
  const [filters, setFilters] = useState<FilterInput>(emptyFilters);
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const [request, setRequest] = useState<{ path: string; mode: Mode; filters: FilterInput } | null>(null);
  function update(key: keyof Draft, value: string | boolean) { setDraft((previous) => ({ ...previous, [key]: value })); }
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const allies = parseIds(draft.allies, 4, "Aliados");
      const opponents = parseIds(draft.opponents, 5, "Adversários");
      if (allies.some((id) => opponents.includes(id))) throw new Error("O mesmo herói não pode estar nos dois lados do draft.");
      const query = appendFilters(new URLSearchParams(), filters);
      allies.forEach((id) => query.append("ally_ids", String(id)));
      opponents.forEach((id) => query.append("opponent_ids", String(id)));
      if (draft.position) query.set("position", draft.position);
      if (mode === "items") {
        const heroId = Number(draft.heroId);
        if (!Number.isInteger(heroId) || heroId < 1 || heroId > 2147483647) throw new Error("Informe um ID de herói válido para recomendar itens.");
        if (allies.includes(heroId) || opponents.includes(heroId)) throw new Error("O herói dos itens não pode aparecer entre aliados ou adversários.");
        query.set("hero_id", draft.heroId);
        query.set("purchase_time_max_seconds", draft.purchaseMax || "1200");
        if (draft.durationMin) query.set("duration_min_seconds", draft.durationMin);
        if (draft.durationMax) query.set("duration_max_seconds", draft.durationMax);
        if (draft.durationMin && draft.durationMax && Number(draft.durationMin) > Number(draft.durationMax)) throw new Error("Duração mínima não pode superar a máxima.");
      }
      query.set("allow_fallback", String(draft.fallback));
      query.set("limit", draft.limit);
      setFormError(null);
      setRequest({ path: `/api/v1/recommendations/${mode}?${query}`, mode, filters });
    } catch (error) { setFormError(error instanceof Error ? error.message : "Contexto inválido."); }
  }
  return <main className="main-shell page-content"><Link className="back-link" href="/">← Voltar à visão geral</Link><div className="page-title"><p className="eyebrow">03 / Recomendações explicáveis</p><h1>Escolhas com contexto.</h1><p>Compare heróis ou primeiras compras registradas. Cada sugestão expõe a amostra, os filtros utilizados e os limites da evidência.</p></div>
    <div className="tab-list" role="group" aria-label="Tipo de recomendação"><button type="button" aria-pressed={mode === "heroes"} className={mode === "heroes" ? "active" : ""} onClick={() => { setMode("heroes"); setRequest(null); setFormError(null); }}>Heróis</button><button type="button" aria-pressed={mode === "items"} className={mode === "items" ? "active" : ""} onClick={() => { setMode("items"); setRequest(null); setFormError(null); }}>Itens</button></div>
    <FilterBar onApply={(next) => { setFilters(next); setRequest(null); }} title="Período e habilidade" />
    <form className="filter-panel draft-panel" onSubmit={submit}><div className="section-heading"><div><p className="eyebrow">Contexto da partida</p><h2>{mode === "heroes" ? "Recomendar heróis" : "Recomendar itens"}</h2></div><p className="subtle">IDs da OpenDota · valores opcionais, exceto o herói para itens</p></div><div className="filter-grid">
      {mode === "items" && <label>ID do herói <input type="number" min="1" max="2147483647" required placeholder="Ex.: 46" value={draft.heroId} onChange={(event) => update("heroId", event.target.value)} /></label>}
      <label>Aliados <input type="text" inputMode="numeric" placeholder="Ex.: 46, 55" value={draft.allies} onChange={(event) => update("allies", event.target.value)} /><small>Até 4 IDs distintos</small></label>
      <label>Adversários <input type="text" inputMode="numeric" placeholder="Ex.: 84, 93" value={draft.opponents} onChange={(event) => update("opponents", event.target.value)} /><small>Até 5 IDs distintos</small></label>
      <label>Posição econômica <select value={draft.position} onChange={(event) => update("position", event.target.value)}><option value="">Qualquer / desconhecida</option>{[1, 2, 3, 4, 5].map((value) => <option value={value} key={value}>Posição {value}</option>)}</select><small>Pode não ter suporte nesta publicação.</small></label>
      <label>Limite de sugestões <input type="number" min="1" max="100" value={draft.limit} onChange={(event) => update("limit", event.target.value)} /></label>
      {mode === "items" && <><label>Compra até (segundos) <input type="number" value={draft.purchaseMax} onChange={(event) => update("purchaseMax", event.target.value)} /><small>Padrão: 1200 s / 20 min</small></label><label>Duração mín. (s) <input type="number" min="1" placeholder="Opcional" value={draft.durationMin} onChange={(event) => update("durationMin", event.target.value)} /></label><label>Duração máx. (s) <input type="number" min="1" placeholder="Opcional" value={draft.durationMax} onChange={(event) => update("durationMax", event.target.value)} /></label></>}
    </div><div className="filter-actions"><label className="check-label"><input type="checkbox" checked={draft.fallback} onChange={(event) => update("fallback", event.target.checked)} /> Permitir recuo de contexto</label><button className="button primary" type="submit">Consultar recomendações <span aria-hidden="true">→</span></button></div>{formError && <p className="form-error" role="alert">{formError}</p>}</form>
    {request ? <RecommendationResults key={request.path} {...request} /> : <div className="state-panel intro-state"><span className="state-symbol">↗</span><h2>Defina o contexto</h2><p>Escolha o tipo de sugestão, ajuste o recorte e consulte. O ranking só aparece quando há evidência suficiente.</p></div>}
  </main>;
}

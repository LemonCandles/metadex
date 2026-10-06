"use client";

import Link from "next/link";
import { useState } from "react";
import { appendFilters, emptyFilters, FilterInput, gameTime, heroName, HeroNames, integer, itemName, minutesToSeconds, parseHeroIds, percent, positionLabels, Recommendation } from "@/lib/api";
import { useHeroCatalogState, useHeroNames, useItemCatalogState, useItemNames } from "@/components/hero-catalog";
import { DataContext, FilterBar, HeroLink, ResourceState, queryFor } from "@/components/ui";
import { useResource } from "@/components/use-resource";

type Mode = "heroes" | "items";
type Draft = { heroId: string; allies: string; opponents: string; fallback: boolean; limit: string; purchaseMax: string; durationMin: string; durationMax: string };
const initialDraft: Draft = { heroId: "", allies: "", opponents: "", fallback: true, limit: "10", purchaseMax: "20", durationMin: "", durationMax: "" };
const levelText = { exact: "Draft informado", without_allies: "Sem filtro de aliados", without_draft: "Sem filtros de aliados e inimigos" };
const statusTitle: Record<Recommendation["status"], string> = { ok: "Sugestões com partidas suficientes", no_data: "Sem partidas com estes filtros", insufficient_evidence: "Poucas partidas para sugerir", unsupported_context: "Filtro indisponível" };

function describeContext(context: Recommendation["requested_context"], names: HeroNames) {
  return [context.hero_id && heroName(names, context.hero_id), context.position && positionLabels[context.position], context.ally_ids.length && `aliados: ${context.ally_ids.map((id) => heroName(names, id)).join(", ")}`, context.opponent_ids.length && `inimigos: ${context.opponent_ids.map((id) => heroName(names, id)).join(", ")}`].filter(Boolean).join(" · ") || "Qualquer composição de heróis";
}

function RecommendationResults({ path, mode, filters }: { path: string; mode: Mode; filters: FilterInput }) {
  const names = useHeroNames();
  const items = useItemNames();
  const { data, loading, error, reload } = useResource<Recommendation>(path);
  return <section className="recommendation-results" aria-live="polite">
    <ResourceState loading={loading} error={error} onRetry={reload} />
    {data && <>
      <DataContext data={data} sampleUnit={mode === "items" ? "purchases" : "picks"} />
      <div className="explanation-panel">
        <p className="eyebrow">Como as sugestões foram escolhidas</p>
        <h2>{data.status === "ok" ? `${integer.format(data.recommendations.length)} ${data.recommendations.length === 1 ? "sugestão" : "sugestões"} com partidas suficientes` : statusTitle[data.status]}</h2>
        <p>{data.explanation}</p>
        <div className="context-pair"><div><span>Seu draft</span><strong>{describeContext(data.requested_context, names)}</strong></div><div><span>Draft usado nas sugestões</span><strong>{describeContext(data.used_context, names)}</strong></div></div>
        {data.fallback.applied && <p className="caution">Para encontrar partidas suficientes, a busca deixou de exigir {data.fallback.removed_filters.map((key) => key === "ally_ids" ? "os aliados informados" : "os inimigos informados").join(" e ")}. Confira acima o draft usado.</p>}
        {!data.supported_contexts.position && <p className="subtle">A coleta não identifica a função de cada jogador no time; estas sugestões não distinguem Carry, Mid, Offlane e suportes.</p>}
        {data.item_timing && <p className="subtle">Primeira compra registrada de cada item até {gameTime(data.item_timing.purchase_time_max_seconds)} no relógio da partida, incluindo o pré-jogo. Duração das partidas: {data.item_timing.duration_min_seconds === null ? "sem mínimo" : `a partir de ${gameTime(data.item_timing.duration_min_seconds)}`}; {data.item_timing.duration_max_seconds === null ? "sem máximo" : `até ${gameTime(data.item_timing.duration_max_seconds)}`}.</p>}
      </div>
      {data.status !== "ok" ? <ResourceState loading={false} error={null} empty emptyMessage={data.explanation} /> : <div className="suggestion-grid">
        {data.recommendations.map((suggestion, index) => <article className="suggestion-card" key={`${suggestion.hero_id}-${suggestion.item_key || "hero"}`}>
          <div className="suggestion-top"><span className="rank-number">{String(index + 1).padStart(2, "0")}</span><span className="sample-tag">{integer.format(suggestion.sample_size)} {mode === "items" ? "compradores" : "picks"}</span></div>
          <h3>{mode === "heroes" ? <HeroLink id={suggestion.hero_id} query={queryFor(filters)} /> : <><span className="item-key">{itemName(items, suggestion.item_key)}</span><small>{heroName(names, suggestion.hero_id)}</small></>}</h3>
          <div className="suggestion-rate"><strong>{percent(suggestion.win_rate)}</strong><span>win rate observado</span></div>
          <p>{suggestion.explanation}</p>
          <dl>
            <div><dt>Vitórias / derrotas</dt><dd>{integer.format(suggestion.wins)} / {integer.format(suggestion.losses)}</dd></div>
            <div><dt>Participações com esse draft</dt><dd>{integer.format(suggestion.context_sample_size)}</dd></div>
            <div><dt>Duração média da partida</dt><dd>{gameTime(suggestion.mean_duration_seconds)}</dd></div>
            {suggestion.mean_purchase_time_seconds !== null && <div><dt>Momento médio da primeira compra</dt><dd>{gameTime(suggestion.mean_purchase_time_seconds)}{suggestion.mean_purchase_time_seconds < 0 && " (pré-jogo)"}</dd></div>}
          </dl>
        </article>)}
      </div>}
      <div className="limitations-panel"><h3>Como interpretar as sugestões</h3><ul>{data.limitations.map((item) => <li key={item}>{item}</li>)}</ul><details><summary>Ver como a busca ampliou o draft</summary><ol>{data.fallback.attempts.map((attempt) => <li key={attempt.level}>{levelText[attempt.level]}: {integer.format(attempt.context_sample_size)} participações, {integer.format(attempt.candidate_count)} candidatos, {integer.format(attempt.eligible_count)} com partidas suficientes.</li>)}</ol></details></div>
    </>}
  </section>;
}

export default function RecommendationsPage() {
  const names = useHeroNames();
  const catalog = useHeroCatalogState();
  const itemCatalog = useItemCatalogState();
  const heroes = Object.entries(names).sort((a, b) => a[1].localeCompare(b[1]));
  const [mode, setMode] = useState<Mode>("heroes");
  const [filters, setFilters] = useState<FilterInput>(emptyFilters);
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const [request, setRequest] = useState<{ path: string; mode: Mode; filters: FilterInput } | null>(null);
  function update(key: keyof Draft, value: string | boolean) { setDraft((previous) => ({ ...previous, [key]: value })); }
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const allies = parseHeroIds(draft.allies, 4, "Aliados", names);
      const opponents = parseHeroIds(draft.opponents, 5, "Inimigos", names);
      if (allies.some((id) => opponents.includes(id))) throw new Error("O mesmo herói não pode estar nos dois times.");
      const query = appendFilters(new URLSearchParams(), filters);
      allies.forEach((id) => query.append("ally_ids", String(id)));
      opponents.forEach((id) => query.append("opponent_ids", String(id)));
      if (mode === "items") {
        const heroId = Number(draft.heroId);
        if (!Number.isInteger(heroId) || heroId < 1 || heroId > 2147483647 || (heroes.length && !names[heroId])) throw new Error("Selecione seu herói para consultar itens.");
        if (allies.includes(heroId) || opponents.includes(heroId)) throw new Error("Seu herói não pode aparecer na lista de aliados ou inimigos.");
        query.set("hero_id", draft.heroId);
        query.set("purchase_time_max_seconds", minutesToSeconds(draft.purchaseMax || "20", "Compra até"));
        if (draft.durationMin) query.set("duration_min_seconds", minutesToSeconds(draft.durationMin, "Duração mínima", 1));
        if (draft.durationMax) query.set("duration_max_seconds", minutesToSeconds(draft.durationMax, "Duração máxima", 1));
        if (draft.durationMin && draft.durationMax && Number(draft.durationMin) > Number(draft.durationMax)) throw new Error("A duração mínima não pode superar a máxima.");
      }
      const limit = Number(draft.limit);
      if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error("Informe de 1 a 100 sugestões.");
      query.set("allow_fallback", String(draft.fallback));
      query.set("limit", String(limit));
      setFormError(null);
      setRequest({ path: `/api/v1/recommendations/${mode}?${query}`, mode, filters });
    } catch (error) { setFormError(error instanceof Error ? error.message : "Draft inválido."); }
  }
  return <main className="main-shell page-content">
    <Link className="back-link" href="/">← Voltar ao meta de heróis</Link>
    <div className="page-title"><p className="eyebrow">03 / Draft e itens</p><h1>Heróis e itens para sua partida.</h1><p>Informe os heróis aliados e inimigos para comparar picks e compras observadas em partidas parecidas. As sugestões mostram win rate e quantidade de partidas.</p></div>
    <div className="tab-list" role="group" aria-label="Tipo de sugestão"><button type="button" aria-pressed={mode === "heroes"} className={mode === "heroes" ? "active" : ""} onClick={() => { setMode("heroes"); setRequest(null); setFormError(null); }}>Heróis para o draft</button><button type="button" aria-pressed={mode === "items"} className={mode === "items" ? "active" : ""} onClick={() => { setMode("items"); setRequest(null); setFormError(null); }}>Itens para seu herói</button></div>
    <FilterBar onApply={(next) => { setFilters(next); setRequest(null); }} title="Período e rank das partidas" />
    {catalog.error && <div className="caution" role="status">Os nomes dos heróis estão indisponíveis. Você pode informar IDs ou <button className="button ghost" type="button" onClick={catalog.reload}>Recarregar nomes</button>.</div>}
    {mode === "items" && itemCatalog.error && <div className="caution" role="status">Os nomes dos itens estão indisponíveis. <button className="button ghost" type="button" onClick={itemCatalog.reload}>Recarregar nomes dos itens</button></div>}
    <form className="filter-panel draft-panel" onSubmit={submit}>
      <div className="section-heading"><div><p className="eyebrow">Composição dos times</p><h2>{mode === "heroes" ? "Encontrar um pick" : "Consultar compras de itens"}</h2></div><p className="subtle">Aliados e inimigos são opcionais</p></div>
      <div className="filter-grid">
        {mode === "items" && <label>{heroes.length ? "Seu herói" : "ID do seu herói"} {heroes.length ? <select required value={draft.heroId} onChange={(event) => update("heroId", event.target.value)}><option value="">Selecione um herói</option>{heroes.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select> : <input type="number" min="1" max="2147483647" required placeholder="Ex.: 46 (Templar Assassin)" value={draft.heroId} onChange={(event) => update("heroId", event.target.value)} />}</label>}
        <label>Heróis aliados <input type="text" list="hero-names" placeholder="Ex.: Templar Assassin, Dark Seer" value={draft.allies} onChange={(event) => update("allies", event.target.value)} /><small>Até 4 outros heróis; separe os nomes por vírgula.</small></label>
        <label>Heróis inimigos <input type="text" list="hero-names" placeholder="Ex.: Ogre Magi, Slark" value={draft.opponents} onChange={(event) => update("opponents", event.target.value)} /><small>Até 5 heróis; separe os nomes por vírgula.</small></label>
        <datalist id="hero-names">{heroes.map(([id, name]) => <option key={id} value={name} />)}</datalist>
        <label>Função no time <select disabled value="" aria-describedby="position-help"><option value="">Sem filtro por função</option>{Object.entries(positionLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select><small id="position-help">Carry, Mid, Offlane e suportes ainda não são identificados na coleta.</small></label>
        <label>Quantidade de sugestões <input type="number" min="1" max="100" required value={draft.limit} onChange={(event) => update("limit", event.target.value)} /></label>
        {mode === "items" && <>
          <label>Primeira compra até (min) <input type="number" step="0.1" value={draft.purchaseMax} onChange={(event) => update("purchaseMax", event.target.value)} /><small>Padrão: 20 min. Inclui compras no pré-jogo; não é uma build ordenada.</small></label>
          <label>Duração mínima da partida (min) <input type="number" min="0.1" step="0.1" placeholder="Opcional" value={draft.durationMin} onChange={(event) => update("durationMin", event.target.value)} /></label>
          <label>Duração máxima da partida (min) <input type="number" min="0.1" step="0.1" placeholder="Opcional" value={draft.durationMax} onChange={(event) => update("durationMax", event.target.value)} /></label>
        </>}
      </div>
      <div className="filter-actions"><label className="check-label"><input type="checkbox" checked={draft.fallback} onChange={(event) => update("fallback", event.target.checked)} /> Ampliar a busca se houver poucas partidas</label><button className="button primary" type="submit">{mode === "heroes" ? "Buscar heróis" : "Buscar itens"} <span aria-hidden="true">→</span></button></div>
      <p className="subtle">Ao ampliar a busca, primeiro retiramos o filtro de aliados, depois o de inimigos. Os heróis já escolhidos continuam fora das sugestões de picks.</p>
      {catalog.loading && <p className="subtle" role="status">Carregando nomes dos heróis…</p>}
      {formError && <p className="form-error" role="alert">{formError}</p>}
    </form>
    {request ? <RecommendationResults key={request.path} {...request} /> : <div className="state-panel intro-state"><span className="state-symbol">↗</span><h2>Monte seu draft</h2><p>Escolha heróis ou itens, aplique os filtros de partidas e informe os times. As sugestões aparecem quando há partidas suficientes.</p></div>}
  </main>;
}

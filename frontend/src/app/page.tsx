"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { appendFilters, emptyFilters, FilterInput, heroName, HeroOrder, integer, percent, Ranking } from "@/lib/api";
import { useHeroNames } from "@/components/hero-catalog";
import { DataContext, EvidenceNote, FilterBar, HeroLink, MetricCard, queryFor, ResourceState } from "@/components/ui";
import { useResource } from "@/components/use-resource";

const orders: { value: HeroOrder; label: string }[] = [
  { value: "win_rate", label: "Win rate (taxa de vitória)" }, { value: "picks", label: "Picks (escolhas)" },
  { value: "wins", label: "Vitórias" }, { value: "pick_rate", label: "Pick rate (taxa de escolha)" },
  { value: "losses", label: "Derrotas" },
];

export default function Home() {
  const names = useHeroNames();
  const [filters, setFilters] = useState<FilterInput>(emptyFilters);
  const [order, setOrder] = useState<HeroOrder>("win_rate");
  const [includeSmall, setIncludeSmall] = useState(false);
  const [search, setSearch] = useState("");
  const path = useMemo(() => {
    const query = appendFilters(new URLSearchParams(), filters);
    query.set("order_by", order); query.set("order", "desc"); query.set("include_below_min", String(includeSmall));
    return `/api/v1/meta/heroes?${query}`;
  }, [filters, order, includeSmall]);
  const { data, loading, error, reload } = useResource<Ranking>(path);
  const searchTerm = search.trim().toLowerCase();
  const heroes = data?.heroes.filter((hero) =>
    heroName(names, hero.hero_id).toLowerCase().includes(searchTerm) ||
    String(hero.hero_id).includes(searchTerm.replace(/^#/, "")),
  ) || [];
  const picks = data?.heroes.reduce((total, hero) => total + hero.picks, 0) || 0;

  return <main className="main-shell">
    <section className="hero-intro"><div><p className="eyebrow">Observatório de Dota 2</p><h1>O meta, com<br /><em>evidência à vista.</em></h1><p>Veja quais heróis são mais escolhidos e vencem nas partidas coletadas. Compare picks, win rate e desempenho ao longo dos dias.</p><div className="hero-actions"><a className="button primary" href="#ranking">Explorar heróis <span aria-hidden="true">↘</span></a><Link className="button secondary" href="/recommendations">Draft e itens <span aria-hidden="true">→</span></Link></div></div><div className="hero-art" aria-hidden="true"><span className="orb orb-one" /><span className="orb orb-two" /><span className="art-grid" /><span className="art-caption">META / DATA / CONTEXT</span></div></section>

    <div className="section-kicker"><span className="live-dot" /> ESTATÍSTICAS DE DOTA 2 <span className="rule" /> 01 / META DE HERÓIS</div>
    <FilterBar onApply={setFilters} />
    <section id="ranking" className="results-section" aria-labelledby="ranking-title">
      <div className="section-heading"><div><p className="eyebrow">Meta de heróis</p><h2 id="ranking-title">Heróis do meta</h2></div><p className="subtle">Estatísticas observadas · sem previsão de vitória</p></div>
      <ResourceState loading={loading} error={error} onRetry={reload} />
      {data && <>
        <DataContext data={data} />
        <div className="metric-grid"><MetricCard label="Partidas analisadas" value={integer.format(data.sample.matches)} note="Base do pick rate" /><MetricCard label="Picks de heróis" value={integer.format(data.sample.participants)} note="10 heróis por partida analisada" /><MetricCard label="Picks nesta lista" value={integer.format(picks)} note={includeSmall ? "Inclui amostras pequenas" : "Heróis com amostra mínima"} /></div>
        <div className="table-panel">
          <div className="table-toolbar"><div><h3>Ranking de heróis</h3><p>{data.status === "below_min_sample" ? "Nenhum herói alcançou a amostra mínima." : `${integer.format(data.heroes.length)} heróis na lista`}</p></div><div className="toolbar-controls"><label>Ordenar por <select value={order} onChange={(event) => setOrder(event.target.value as HeroOrder)}>{orders.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label className="check-label"><input type="checkbox" checked={includeSmall} onChange={(event) => setIncludeSmall(event.target.checked)} /> Mostrar amostras pequenas</label><label>Buscar herói <input className="search-input" type="search" placeholder="Ex.: Anti-Mage" value={search} onChange={(event) => setSearch(event.target.value)} /></label></div></div>
          {data.heroes.length > 0 && heroes.length === 0 ? <ResourceState loading={false} error={null} empty emptyMessage="Nenhum herói da lista corresponde à busca." /> : data.heroes.length > 0 ? <div className="table-scroll"><table><caption className="sr-only">Heróis, picks, vitórias, derrotas, pick rate, win rate e tamanho da amostra</caption><thead><tr><th scope="col">Herói</th><th scope="col">Picks</th><th scope="col">Vitórias</th><th scope="col">Derrotas</th><th scope="col">Pick rate</th><th scope="col">Win rate</th><th scope="col">Amostra</th></tr></thead><tbody>{heroes.map((hero) => <tr key={hero.hero_id}><th scope="row"><HeroLink id={hero.hero_id} query={queryFor(filters)} /></th><td>{integer.format(hero.picks)}</td><td>{integer.format(hero.wins)}</td><td>{integer.format(hero.losses)}</td><td>{percent(hero.pick_rate)}</td><td><span className="rate-cell">{percent(hero.win_rate)}<span className="rate-track" aria-hidden="true"><span style={{ width: `${(hero.win_rate || 0) * 100}%` }} /></span></span></td><td><span className={hero.meets_min_sample ? "sample-tag" : "sample-tag warning"}>{integer.format(hero.sample_size)}{!hero.meets_min_sample && " · pequena"}</span></td></tr>)}</tbody></table></div> : <ResourceState loading={false} error={null} empty emptyMessage={data.status === "below_min_sample" ? `Há partidas, mas nenhum herói alcançou ${integer.format(data.sample.min_sample_size)} picks. Ative “Mostrar amostras pequenas” para explorar esses dados.` : "Não há partidas com estes filtros. Ajuste o período ou os filtros."} />}
        </div>
        <EvidenceNote />
      </>}
    </section>
  </main>;
}

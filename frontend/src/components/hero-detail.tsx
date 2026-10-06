"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { appendFilters, Detail, filtersFromQuery, FilterInput, heroName, integer, percent, signedPercent, Trend, utcDate } from "@/lib/api";
import { useHeroNames } from "@/components/hero-catalog";
import { DataContext, EvidenceNote, FilterBar, MetricCard, ResourceState } from "@/components/ui";
import { useResource } from "@/components/use-resource";

const comparisonText: Record<Trend["comparison"]["status"], string> = {
  comparable: "Janelas comparáveis: diferenças calculadas com os mesmos filtros e dias com partidas em ambas.",
  insufficient_history: "Histórico insuficiente na janela anterior; diferenças não calculadas.",
  incomplete_current_period: "Há dias sem partidas na janela atual; diferenças não calculadas.",
  no_current_data: "Nenhuma partida elegível na janela atual; diferenças não calculadas.",
};

function TrendChart({ trend }: { trend: Trend }) {
  const width = 700, height = 190, left = 35, top = 12;
  const plotWidth = width - left - 10;
  const x = (index: number) => left + (trend.points.length <= 1 ? plotWidth / 2 : index * plotWidth / (trend.points.length - 1));
  const y = (rate: number) => top + (1 - rate) * height;
  const segments: string[] = [];
  let current: string[] = [];
  trend.points.forEach((point, index) => {
    if (point.win_rate === null || !point.has_data) { if (current.length) segments.push(current.join(" ")); current = []; }
    else current.push(`${x(index)},${y(point.win_rate)}`);
  });
  if (current.length) segments.push(current.join(" "));
  return <div className="chart-panel"><div className="section-heading"><div><p className="eyebrow">Tendência diária</p><h3 id="trend-section">Win rate por dia</h3></div><span className="legend"><i /> Vitórias / picks</span></div>
    <div className="chart-scroll"><svg viewBox="0 0 700 240" role="img" aria-labelledby="trend-title trend-desc" preserveAspectRatio="xMidYMid meet"><title id="trend-title">Tendência diária da taxa de vitória</title><desc id="trend-desc">Linha da taxa de vitória diária; dias sem partidas ou escolhas interrompem a linha. Os números completos estão na tabela abaixo.</desc>
      {[0, .25, .5, .75, 1].map((rate) => <g key={rate}><line className="gridline" x1={left} x2={width - 10} y1={y(rate)} y2={y(rate)} /><text className="axis-label" x="0" y={y(rate) + 4}>{Math.round(rate * 100)}%</text></g>)}
      {segments.map((segment, index) => segment.includes(" ") ? <polyline key={index} className="trend-line" points={segment} /> : <circle key={index} className="trend-dot" cx={Number(segment.split(",")[0])} cy={Number(segment.split(",")[1])} r="4" />)}
      {trend.points.map((point, index) => point.win_rate !== null && point.has_data ? <circle key={point.date} className="trend-dot" cx={x(index)} cy={y(point.win_rate)} r="3" /> : null)}
      {[0, Math.floor((trend.points.length - 1) / 2), trend.points.length - 1].filter((index, position, array) => index >= 0 && array.indexOf(index) === position).map((index) => <text key={index} className="axis-label" x={x(index)} y="230" textAnchor={index === 0 ? "start" : index === trend.points.length - 1 ? "end" : "middle"}>{utcDate(trend.points[index].date)}</text>)}
    </svg></div>
    <p className="subtle">Dias sem denominador aparecem como lacunas. A linha descreve observações, não prevê resultados.</p>
    <details className="daily-details"><summary>Ver dados diários em tabela</summary><div className="table-scroll"><table><thead><tr><th scope="col">Dia (UTC)</th><th scope="col">Partidas</th><th scope="col">Picks</th><th scope="col">Vitórias</th><th scope="col">Win rate</th></tr></thead><tbody>{trend.points.map((point) => <tr key={point.date}><th scope="row">{utcDate(point.date)}</th><td>{integer.format(point.matches)}</td><td>{integer.format(point.picks)}</td><td>{integer.format(point.wins)}</td><td>{percent(point.win_rate)}</td></tr>)}</tbody></table></div></details>
  </div>;
}

export function HeroDetailPage({ heroId, initialQuery }: { heroId: number; initialQuery: string }) {
  const names = useHeroNames();
  const initial = useMemo(() => filtersFromQuery(new URLSearchParams(initialQuery)), [initialQuery]);
  const [filters, setFilters] = useState<FilterInput>(initial);
  const query = useMemo(() => appendFilters(new URLSearchParams(), filters).toString(), [filters]);
  const detail = useResource<Detail>(`/api/v1/meta/heroes/${heroId}?${query}`);
  const trend = useResource<Trend>(`/api/v1/meta/heroes/${heroId}/trend?${query}`);
  const data = detail.data;
  return <main className="main-shell page-content"><Link className="back-link" href="/">← Voltar ao ranking</Link><div className="page-title"><p className="eyebrow">02 / Detalhe do herói</p><h1>{heroName(names, heroId)}</h1><p>Picks, win rate e evolução diária nas partidas analisadas.</p></div>
    <FilterBar initial={initial} onApply={setFilters} title="Filtrar este herói" />
    <ResourceState loading={detail.loading} error={detail.error} onRetry={detail.reload} />
    {data && <><DataContext data={data} /><div className="metric-grid four"><MetricCard label="Picks (escolhas)" value={integer.format(data.hero.picks)} note={`Amostra do herói · mínimo ${integer.format(data.sample.min_sample_size)}`} /><MetricCard label="Vitórias / derrotas" value={`${integer.format(data.hero.wins)} / ${integer.format(data.hero.losses)}`} note="Resultados observados" /><MetricCard label="Pick rate" value={percent(data.hero.pick_rate)} note="Partidas com o herói ÷ partidas analisadas" /><MetricCard label="Win rate" value={percent(data.hero.win_rate)} note="Vitórias ÷ picks do herói" /></div>
      {!data.hero.meets_min_sample && <p className="caution" role="status">Amostra pequena: este herói teve {integer.format(data.hero.sample_size)} picks, abaixo do mínimo de {integer.format(data.sample.min_sample_size)}. Interprete as taxas com cautela.</p>}
      <section aria-labelledby="trend-section"><ResourceState loading={trend.loading} error={trend.error} onRetry={trend.reload} />{trend.data && <><TrendChart trend={trend.data} /><div className="comparison-panel"><div><p className="eyebrow">Janela anterior · {utcDate(trend.data.comparison.period.start)} a {utcDate(trend.data.comparison.period.end)} UTC (fim exclusivo)</p><h3>Comparação com o período anterior</h3><p>{comparisonText[trend.data.comparison.status]}</p><small>{integer.format(trend.data.comparison.sample.matches)} partidas anteriores · {integer.format(trend.data.comparison.hero.sample_size)} picks do herói</small></div><div className="comparison-values"><span>Variação do pick rate <strong>{signedPercent(trend.data.comparison.pick_rate_delta)}</strong></span><span>Variação do win rate <strong>{signedPercent(trend.data.comparison.win_rate_delta)}</strong></span></div></div></>}</section><EvidenceNote />
    </>}
  </main>;
}

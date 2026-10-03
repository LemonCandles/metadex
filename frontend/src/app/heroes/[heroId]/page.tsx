import { notFound } from "next/navigation";
import { HeroDetailPage } from "@/components/hero-detail";

export default async function Page({ params, searchParams }: { params: Promise<{ heroId: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { heroId } = await params;
  const id = Number(heroId);
  if (!Number.isInteger(id) || id < 1 || id > 2147483647) notFound();
  const values = await searchParams;
  const query = new URLSearchParams();
  for (const key of ["period_start", "period_end", "cohort", "skill_min", "skill_max", "rank_coverage_min"]) {
    const value = values[key];
    if (typeof value === "string") query.set(key, value);
  }
  return <HeroDetailPage heroId={id} initialQuery={query.toString()} />;
}

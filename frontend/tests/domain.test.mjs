import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";

// Exercise the same TypeScript helpers used by the forms, without an extra test dependency.
const source = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const api = {};
vm.runInNewContext(compiled, { exports: api, process, URLSearchParams, Intl, Date });
const names = { 1: "Anti-Mage", 46: "Templar Assassin", 55: "Dark Seer", 84: "Ogre Magi" };

test("draft accepts full game names and mixed IDs without splitting spaces", () => {
  assert.equal(JSON.stringify(api.parseHeroIds("Templar Assassin, Dark Seer; #84", 4, "Aliados", names)), "[46,55,84]");
  assert.equal(JSON.stringify(api.parseHeroIds("46 55", 4, "Aliados", names)), "[46,55]");
  assert.equal(JSON.stringify(api.parseHeroIds(" anti-mage ", 4, "Aliados", names)), "[1]");
});

test("draft rejects duplicated, unknown and excessive heroes", () => {
  for (const input of ["Anti-Mage, #1", "Templar Assasin", "999", "1,46,55,84"]) {
    assert.throws(() => api.parseHeroIds(input, 3, "Aliados", names));
  }
  assert.equal(JSON.stringify(api.parseHeroIds("", 4, "Aliados", names)), "[]");
  assert.equal(JSON.stringify(api.parseHeroIds("46", 4, "Aliados", {})), "[46]");
});

test("items preserve the exact catalog name and explicitly handle missing labels", () => {
  assert.equal(api.itemName({ black_king_bar: "Black King Bar" }, "black_king_bar"), "Black King Bar");
  assert.match(api.itemName({}, "new_item"), /sem nome no catálogo/);
  assert.equal(api.heroName(names, 46), "Templar Assassin");
});

test("rank labels distinguish medals, stars and fractional match averages", () => {
  assert.equal(api.rankLabel(11), "Herald 1 ★");
  assert.equal(api.rankLabel(75), "Divine 5 ★");
  assert.equal(api.rankLabel(80), "Immortal");
  assert.equal(api.rankLabel(85), "Immortal");
  assert.equal(api.rankLabel(73.5), "Divine (média 73,5)");
});

test("minutes sent by the item form convert to seconds including pregame", () => {
  assert.equal(api.minutesToSeconds("20", "Compra"), "1200");
  assert.equal(api.minutesToSeconds("12.5", "Compra"), "750");
  assert.equal(api.minutesToSeconds("-1", "Compra"), "-60");
  assert.equal(api.minutesToSeconds("30", "Duração", 1), "1800");
  for (const value of ["", "Infinity", "invalid", "999999999"]) {
    assert.throws(() => api.minutesToSeconds(value, "Compra"));
  }
  assert.throws(() => api.minutesToSeconds("0", "Duração", 1));
});

test("match clock displays zero, fractional means and negative pregame times", () => {
  assert.equal(api.gameTime(0), "0:00");
  assert.equal(api.gameTime(1200), "20:00");
  assert.equal(api.gameTime(89.6), "1:30");
  assert.equal(api.gameTime(-50), "−0:50");
});

test("filters reject invalid rank ranges, coverage and periods", () => {
  const filters = { ...api.emptyFilters, skill_min: "71", skill_max: "75", rank_coverage_min: "5" };
  assert.equal(api.validateFilters(filters), null);
  for (const changes of [{ skill_min: "80" }, { skill_max: "86" }, { skill_min: "abc" }, { rank_coverage_min: "1.5" }, { rank_coverage_min: "11" }, { period_start: "2026-10-01" }, { period_start: "2026-10-02", period_end: "2026-10-01" }]) {
    assert.ok(api.validateFilters({ ...filters, ...changes }));
  }
  assert.equal(api.validateFilters({ ...filters, period_start: "2026-10-01", period_end: "2026-10-02" }), null);
});

test("filters keep rank IDs in the API query while labels stay in the UI", () => {
  const query = api.appendFilters(new URLSearchParams(), { ...api.emptyFilters, skill_min: "71", skill_max: "75" });
  assert.equal(query.get("skill_min"), "71");
  assert.equal(query.get("skill_max"), "75");
  assert.equal(query.get("cohort"), "all");
});

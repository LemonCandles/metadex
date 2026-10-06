"use client";

import { createContext, useContext, useMemo } from "react";
import { HeroCatalog, HeroNames, ItemCatalog, ItemNames } from "@/lib/api";
import { useResource } from "@/components/use-resource";

const HeroCatalogContext = createContext<HeroNames>({});
const ItemCatalogContext = createContext<ItemNames>({});
const HeroCatalogStateContext = createContext({ loading: true, error: null as string | null, reload: () => {} });
const ItemCatalogStateContext = createContext({ loading: true, error: null as string | null, reload: () => {} });

export function HeroCatalogProvider({ children }: { children: React.ReactNode }) {
  const { data, loading, error, reload } = useResource<HeroCatalog>("/api/v1/catalog/heroes");
  const { data: items, loading: itemsLoading, error: itemsError, reload: reloadItems } = useResource<ItemCatalog>("/api/v1/catalog/items");
  const names = useMemo(() => Object.fromEntries(
    (data?.heroes || []).map((hero) => [hero.hero_id, hero.name]),
  ), [data]);
  const itemNames = useMemo(() => Object.fromEntries(
    (items?.items || []).map((item) => [item.item_key, item.name]),
  ), [items]);
  return <HeroCatalogStateContext.Provider value={{ loading, error, reload }}><ItemCatalogStateContext.Provider value={{ loading: itemsLoading, error: itemsError, reload: reloadItems }}><HeroCatalogContext.Provider value={names}><ItemCatalogContext.Provider value={itemNames}>{children}</ItemCatalogContext.Provider></HeroCatalogContext.Provider></ItemCatalogStateContext.Provider></HeroCatalogStateContext.Provider>;
}

export function useHeroNames() {
  return useContext(HeroCatalogContext);
}

export function useItemNames() { return useContext(ItemCatalogContext); }
export function useHeroCatalogState() { return useContext(HeroCatalogStateContext); }
export function useItemCatalogState() { return useContext(ItemCatalogStateContext); }

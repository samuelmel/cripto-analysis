import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  assetDetailSchema,
  marketSchema,
  overviewSchema,
  portfolioDetailSchema,
  portfoliosSchema,
  researchSchema,
  type AssetDetail,
  type MarketData,
  type Overview,
  type PortfolioDetail,
  type PortfoliosData,
  type ResearchData,
} from "../schemas/api";
import { getJson } from "./api";

const LONG = 5 * 60 * 1000;

export function useOverview(): UseQueryResult<Overview> {
  return useQuery({
    queryKey: ["overview"],
    queryFn: ({ signal }) => getJson("/overview", overviewSchema, signal),
    staleTime: LONG,
  });
}

export function useMarket(): UseQueryResult<MarketData> {
  return useQuery({
    queryKey: ["market"],
    queryFn: ({ signal }) => getJson("/market", marketSchema, signal),
    staleTime: LONG,
  });
}

export function useAsset(symbol: string, days = 365): UseQueryResult<AssetDetail> {
  return useQuery({
    queryKey: ["asset", symbol, days],
    queryFn: ({ signal }) => getJson(`/assets/${encodeURIComponent(symbol)}?days=${days}`, assetDetailSchema, signal),
    staleTime: LONG,
    enabled: symbol.length > 0,
  });
}

export function useResearch(): UseQueryResult<ResearchData> {
  return useQuery({
    queryKey: ["research"],
    queryFn: ({ signal }) => getJson("/research", researchSchema, signal),
    staleTime: LONG,
  });
}

export function usePortfolios(): UseQueryResult<PortfoliosData> {
  return useQuery({
    queryKey: ["portfolios"],
    queryFn: ({ signal }) => getJson("/portfolios", portfoliosSchema, signal),
    staleTime: LONG,
  });
}

export function usePortfolio(id: string): UseQueryResult<PortfolioDetail> {
  return useQuery({
    queryKey: ["portfolio", id],
    queryFn: ({ signal }) => getJson(`/portfolios/${encodeURIComponent(id)}`, portfolioDetailSchema, signal),
    staleTime: LONG,
    enabled: id.length > 0,
  });
}

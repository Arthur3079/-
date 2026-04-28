import { useQuery } from "@tanstack/react-query";
import { apiFetch, analyticsSummarySchema, type AnalyticsSummary } from "@/api";

export function useAnalyticsSummary() {
  return useQuery<AnalyticsSummary>({
    queryKey: ["analytics", "summary"],
    queryFn: async () => {
      const raw = await apiFetch<unknown>("/combine/analytics/summary");
      return analyticsSummarySchema.parse(raw);
    },
    retry: 1,
    staleTime: 30_000,
  });
}

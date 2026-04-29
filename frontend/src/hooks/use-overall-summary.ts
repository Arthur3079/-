import { useQuery } from "@tanstack/react-query";
import { apiFetch, overallSummarySchema, type OverallSummary } from "@/api";

const KEY = ["combine", "analytics", "summary"] as const;

export function useOverallSummary() {
  return useQuery<OverallSummary>({
    queryKey: KEY,
    queryFn: async () => {
      const raw = await apiFetch<unknown>("/combine/analytics/summary");
      return overallSummarySchema.parse(raw);
    },
    staleTime: 30_000,
  });
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiFetch,
  warmingJobListSchema,
  warmingJobOutSchema,
  warmingJobDetailOutSchema,
  type WarmingJobOut,
  type WarmingJobDetailOut,
} from "@/api";

const KEY = ["combine", "warming"] as const;

export interface WarmingJobInput {
  account_id: number;
  note?: string | null;
  seed?: number | null;
  plan?: {
    duration_days?: number | null;
    actions_per_day_min?: number | null;
    actions_per_day_max?: number | null;
    target_trust_score?: number | null;
  } | null;
}

export function useWarmingJobs() {
  return useQuery<WarmingJobOut[]>({
    queryKey: KEY,
    queryFn: async () => {
      const raw = await apiFetch<unknown>("/combine/warming/jobs");
      return warmingJobListSchema.parse(raw);
    },
    staleTime: 30_000,
  });
}

export function useCreateWarmingJob() {
  const qc = useQueryClient();
  return useMutation<WarmingJobDetailOut, Error, WarmingJobInput>({
    mutationFn: async (input) => {
      const raw = await apiFetch<unknown>("/combine/warming/jobs", {
        method: "POST",
        body: input,
      });
      return warmingJobDetailOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function usePauseWarmingJob() {
  const qc = useQueryClient();
  return useMutation<WarmingJobOut, Error, number>({
    mutationFn: async (id) => {
      const raw = await apiFetch<unknown>(`/combine/warming/jobs/${id}/pause`, {
        method: "POST",
      });
      return warmingJobOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useResumeWarmingJob() {
  const qc = useQueryClient();
  return useMutation<WarmingJobOut, Error, number>({
    mutationFn: async (id) => {
      const raw = await apiFetch<unknown>(`/combine/warming/jobs/${id}/resume`, {
        method: "POST",
      });
      return warmingJobOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useCancelWarmingJob() {
  const qc = useQueryClient();
  return useMutation<WarmingJobOut, Error, number>({
    mutationFn: async (id) => {
      const raw = await apiFetch<unknown>(`/combine/warming/jobs/${id}/cancel`, {
        method: "POST",
      });
      return warmingJobOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteWarmingJob() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await apiFetch<void>(`/combine/warming/jobs/${id}`, { method: "DELETE" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

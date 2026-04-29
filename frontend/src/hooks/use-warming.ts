import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiFetch,
  warmingJobOutSchema,
  warmingJobListSchema,
  type WarmingJobOut,
} from "@/api";

const KEY = ["combine", "warming", "jobs"] as const;

export interface WarmingJobInput {
  account_id: number;
  note?: string | null;
  seed?: number | null;
}

export function useWarmingJobs() {
  return useQuery<WarmingJobOut[]>({
    queryKey: KEY,
    queryFn: async () => {
      const raw = await apiFetch<unknown>("/combine/warming/jobs");
      return warmingJobListSchema.parse(raw);
    },
    staleTime: 15_000,
  });
}

export function useCreateWarmingJob() {
  const qc = useQueryClient();
  return useMutation<WarmingJobOut, Error, WarmingJobInput>({
    mutationFn: async (input) => {
      const raw = await apiFetch<unknown>("/combine/warming/jobs", {
        method: "POST",
        body: input,
      });
      // The detail schema extends the list schema, so the list-shape parse works.
      return warmingJobOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

function jobAction(action: "pause" | "resume" | "cancel") {
  return (id: number) =>
    apiFetch<unknown>(`/combine/warming/jobs/${id}/${action}`, {
      method: "POST",
    }).then((raw) => warmingJobOutSchema.parse(raw));
}

export function usePauseWarming() {
  const qc = useQueryClient();
  return useMutation<WarmingJobOut, Error, number>({
    mutationFn: jobAction("pause"),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useResumeWarming() {
  const qc = useQueryClient();
  return useMutation<WarmingJobOut, Error, number>({
    mutationFn: jobAction("resume"),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useCancelWarming() {
  const qc = useQueryClient();
  return useMutation<WarmingJobOut, Error, number>({
    mutationFn: jobAction("cancel"),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteWarming() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await apiFetch<void>(`/combine/warming/jobs/${id}`, { method: "DELETE" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

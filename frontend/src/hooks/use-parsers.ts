import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiFetch,
  parserJobListSchema,
  parserJobOutSchema,
  parserResultsPageSchema,
  type ParserJobOut,
  type ParserKind,
  type ParserResultsPage,
} from "@/api";

const KEY = ["combine", "parsers"] as const;

export interface ParserJobInput {
  account_id: number;
  kind: ParserKind;
  target: string;
  params?: Record<string, unknown>;
  note?: string | null;
}

export function useParserJobs() {
  return useQuery<ParserJobOut[]>({
    queryKey: KEY,
    queryFn: async () => {
      const raw = await apiFetch<unknown>("/combine/parsers/jobs");
      return parserJobListSchema.parse(raw);
    },
    staleTime: 30_000,
  });
}

export function useCreateParserJob() {
  const qc = useQueryClient();
  return useMutation<ParserJobOut, Error, ParserJobInput>({
    mutationFn: async (input) => {
      const raw = await apiFetch<unknown>("/combine/parsers/jobs", {
        method: "POST",
        body: input,
      });
      return parserJobOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteParserJob() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await apiFetch<void>(`/combine/parsers/jobs/${id}`, { method: "DELETE" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useParserResults(jobId: number | null) {
  return useQuery<ParserResultsPage>({
    queryKey: ["combine", "parsers", "results", jobId],
    queryFn: async () => {
      const raw = await apiFetch<unknown>(
        `/combine/parsers/jobs/${jobId}/results?limit=100`,
      );
      return parserResultsPageSchema.parse(raw);
    },
    enabled: jobId !== null,
    staleTime: 15_000,
  });
}

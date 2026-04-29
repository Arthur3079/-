import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiFetch,
  parserJobOutSchema,
  parserJobListSchema,
  type ParserJobOut,
  type ParserKind,
} from "@/api";

const KEY = ["combine", "parsers", "jobs"] as const;

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
    staleTime: 15_000,
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

export function useCancelParser() {
  const qc = useQueryClient();
  return useMutation<ParserJobOut, Error, number>({
    mutationFn: async (id) => {
      const raw = await apiFetch<unknown>(
        `/combine/parsers/jobs/${id}/cancel`,
        { method: "POST" },
      );
      return parserJobOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useRunParserStub() {
  const qc = useQueryClient();
  return useMutation<ParserJobOut, Error, number>({
    mutationFn: async (id) => {
      const raw = await apiFetch<unknown>(
        `/combine/parsers/jobs/${id}/run-stub`,
        { method: "POST", body: {} },
      );
      return parserJobOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteParser() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await apiFetch<void>(`/combine/parsers/jobs/${id}`, { method: "DELETE" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

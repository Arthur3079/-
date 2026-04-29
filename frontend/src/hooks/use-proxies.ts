import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiFetch,
  proxyListSchema,
  proxyOutSchema,
  proxyHealthOutSchema,
  type ProxyOut,
  type ProxyType,
  type ProxyHealthOut,
} from "@/api";

const PROXIES_KEY = ["combine", "proxies"] as const;

export interface ProxyInput {
  type: ProxyType;
  host: string;
  port: number;
  username?: string | null;
  password?: string | null;
  mtproto_secret?: string | null;
  note?: string | null;
}

export function useProxies() {
  return useQuery<ProxyOut[]>({
    queryKey: PROXIES_KEY,
    queryFn: async () => {
      const raw = await apiFetch<unknown>("/combine/proxies");
      return proxyListSchema.parse(raw);
    },
    staleTime: 30_000,
  });
}

export function useCreateProxy() {
  const qc = useQueryClient();
  return useMutation<ProxyOut, Error, ProxyInput>({
    mutationFn: async (input) => {
      const raw = await apiFetch<unknown>("/combine/proxies", {
        method: "POST",
        body: input,
      });
      return proxyOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: PROXIES_KEY }),
  });
}

export function useDeleteProxy() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await apiFetch<void>(`/combine/proxies/${id}`, { method: "DELETE" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: PROXIES_KEY }),
  });
}

export function useCheckProxy() {
  const qc = useQueryClient();
  return useMutation<ProxyHealthOut, Error, number>({
    mutationFn: async (id) => {
      const raw = await apiFetch<unknown>(`/combine/proxies/${id}/check`, {
        method: "POST",
      });
      return proxyHealthOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: PROXIES_KEY }),
  });
}

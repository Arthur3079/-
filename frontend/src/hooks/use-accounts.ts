import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiFetch,
  accountListSchema,
  accountOutSchema,
  loginStartOutSchema,
  loginCodeOutSchema,
  loginPasswordOutSchema,
  healthCheckOutSchema,
  type AccountOut,
  type AccountRole,
  type LoginStartOut,
  type LoginCodeOut,
  type LoginPasswordOut,
  type HealthCheckOut,
} from "@/api";

const ACCOUNTS_KEY = ["combine", "accounts"] as const;

export interface AccountInput {
  phone: string;
  role?: AccountRole;
  proxy_id?: number | null;
  api_id?: number | null;
  api_hash?: string | null;
  note?: string | null;
}

export function useAccounts() {
  return useQuery<AccountOut[]>({
    queryKey: ACCOUNTS_KEY,
    queryFn: async () => {
      const raw = await apiFetch<unknown>("/combine/accounts");
      return accountListSchema.parse(raw);
    },
    staleTime: 30_000,
  });
}

export function useCreateAccount() {
  const qc = useQueryClient();
  return useMutation<AccountOut, Error, AccountInput>({
    mutationFn: async (input) => {
      const raw = await apiFetch<unknown>("/combine/accounts", {
        method: "POST",
        body: input,
      });
      return accountOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export function useDeleteAccount() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await apiFetch<void>(`/combine/accounts/${id}`, { method: "DELETE" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export function useHealthCheck() {
  const qc = useQueryClient();
  return useMutation<HealthCheckOut, Error, number>({
    mutationFn: async (id) => {
      const raw = await apiFetch<unknown>(`/combine/accounts/${id}/health`, {
        method: "POST",
      });
      return healthCheckOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation<AccountOut, Error, number>({
    mutationFn: async (id) => {
      const raw = await apiFetch<unknown>(`/combine/accounts/${id}/logout`, {
        method: "POST",
      });
      return accountOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

// ---- login flow ----

export interface LoginStartInput {
  account_id: number;
  api_id?: number | null;
  api_hash?: string | null;
}

export function useLoginStart() {
  return useMutation<LoginStartOut, Error, LoginStartInput>({
    mutationFn: async ({ account_id, api_id, api_hash }) => {
      const body: Record<string, unknown> = {};
      if (api_id != null) body.api_id = api_id;
      if (api_hash) body.api_hash = api_hash;
      const raw = await apiFetch<unknown>(
        `/combine/accounts/${account_id}/login/start`,
        {
          method: "POST",
          body,
        },
      );
      return loginStartOutSchema.parse(raw);
    },
  });
}

export interface LoginCodeInput {
  account_id: number;
  login_token: string;
  code: string;
}

export function useLoginCode() {
  const qc = useQueryClient();
  return useMutation<LoginCodeOut, Error, LoginCodeInput>({
    mutationFn: async ({ account_id, login_token, code }) => {
      const raw = await apiFetch<unknown>(
        `/combine/accounts/${account_id}/login/code`,
        {
          method: "POST",
          body: { login_token, code },
        },
      );
      return loginCodeOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export interface LoginPasswordInput {
  account_id: number;
  login_token: string;
  password: string;
}

export function useLoginPassword() {
  const qc = useQueryClient();
  return useMutation<LoginPasswordOut, Error, LoginPasswordInput>({
    mutationFn: async ({ account_id, login_token, password }) => {
      const raw = await apiFetch<unknown>(
        `/combine/accounts/${account_id}/login/password`,
        {
          method: "POST",
          body: { login_token, password },
        },
      );
      return loginPasswordOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export function useLoginCancel() {
  return useMutation<void, Error, number>({
    mutationFn: async (account_id) => {
      await apiFetch<void>(`/combine/accounts/${account_id}/login/cancel`, {
        method: "POST",
      });
    },
  });
}

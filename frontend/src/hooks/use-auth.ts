import { useMutation, useQuery } from "@tanstack/react-query";
import {
  apiFetch,
  tokenOutSchema,
  userOutSchema,
  type TokenOut,
  type UserOut,
} from "@/api";
import { useAuthStore } from "@/stores/auth";

export interface LoginInput {
  login: string;
  password: string;
}

export interface RegisterInput {
  login: string;
  password: string;
  workspace_name?: string;
}

export function useLogin() {
  return useMutation<TokenOut, Error, LoginInput>({
    mutationFn: async (input) => {
      const raw = await apiFetch<unknown>("/auth/login", {
        method: "POST",
        body: input,
      });
      const token = tokenOutSchema.parse(raw);
      useAuthStore.getState().setToken(token.access_token);
      // fetch /me right away so sidebar has user info
      try {
        const me = await apiFetch<unknown>("/auth/me");
        useAuthStore.getState().setUser(userOutSchema.parse(me));
      } catch {
        // non-fatal — user may still navigate; useCurrentUser will retry later
      }
      return token;
    },
  });
}

export function useRegister() {
  return useMutation<TokenOut, Error, RegisterInput>({
    mutationFn: async (input) => {
      const raw = await apiFetch<unknown>("/auth/register", {
        method: "POST",
        body: input,
      });
      const token = tokenOutSchema.parse(raw);
      useAuthStore.getState().setToken(token.access_token);
      try {
        const me = await apiFetch<unknown>("/auth/me");
        useAuthStore.getState().setUser(userOutSchema.parse(me));
      } catch {
        // ignore
      }
      return token;
    },
  });
}

export function useLogout() {
  return () => {
    useAuthStore.getState().clear();
  };
}

export function useCurrentUser() {
  const token = useAuthStore((s) => s.token);
  return useQuery<UserOut>({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const raw = await apiFetch<unknown>("/auth/me");
      const user = userOutSchema.parse(raw);
      useAuthStore.getState().setUser(user);
      return user;
    },
    enabled: !!token,
    staleTime: 60_000,
    retry: false,
  });
}

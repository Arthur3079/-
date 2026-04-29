import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { router, ROUTER_BASENAME } from "./router";

function onUnauthorized(err: unknown) {
  if (!(err instanceof ApiError) || err.status !== 401) return;
  useAuthStore.getState().clear();
  // Drop every cached query so the next user never sees stale data from
  // the previous session (multi-tenant data separation).
  queryClient.clear();
  if (typeof window === "undefined") return;

  // Router navigation respects the configured basename, so calling
  // router.navigate("/login") resolves to `${ROUTER_BASENAME}/login`.
  const loginPath = `${ROUTER_BASENAME}/login`.replace(/\/+/g, "/");
  if (window.location.pathname !== loginPath) {
    router.navigate("/login", { replace: true });
  }
}

const queryClient: QueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
    },
  },
  queryCache: new QueryCache({ onError: onUnauthorized }),
  mutationCache: new MutationCache({ onError: onUnauthorized }),
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

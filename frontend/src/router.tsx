import { Navigate, createBrowserRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { RootLayout } from "@/layouts/root-layout";
import { DashboardPage } from "@/pages/dashboard";
import { AccountsPage } from "@/pages/accounts";
import { ProxiesPage } from "@/pages/proxies";
import { WarmingPage } from "@/pages/warming";
import { ParsersPage } from "@/pages/parsers";
import { CommentingPage } from "@/pages/commenting";
import { ReactionsPage } from "@/pages/reactions";
import { AnalyticsPage } from "@/pages/analytics";
import { LoginPage } from "@/pages/login";
import { useAuthStore } from "@/stores/auth";

function RequireAuth({ children }: { children: ReactNode }) {
  const token = useAuthStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

// Keep in sync with `base` in vite.config.ts and the FastAPI mount in
// sonya_web/app.py. Trailing slash is trimmed because React Router's
// basename expects no trailing slash.
export const ROUTER_BASENAME = (
  import.meta.env.BASE_URL ?? "/"
).replace(/\/$/, "");

export const router = createBrowserRouter(
  [
    { path: "/login", element: <LoginPage /> },
    {
      element: (
        <RequireAuth>
          <RootLayout />
        </RequireAuth>
      ),
      children: [
        { index: true, element: <DashboardPage /> },
        { path: "accounts", element: <AccountsPage /> },
        { path: "proxies", element: <ProxiesPage /> },
        { path: "warming", element: <WarmingPage /> },
        { path: "parsers", element: <ParsersPage /> },
        { path: "commenting", element: <CommentingPage /> },
        { path: "reactions", element: <ReactionsPage /> },
        { path: "analytics", element: <AnalyticsPage /> },
      ],
    },
  ],
  { basename: ROUTER_BASENAME || undefined },
);

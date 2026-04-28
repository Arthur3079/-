import { createBrowserRouter } from "react-router-dom";
import { RootLayout } from "@/layouts/root-layout";
import { DashboardPage } from "@/pages/dashboard";
import { AccountsPage } from "@/pages/accounts";
import { ProxiesPage } from "@/pages/proxies";
import { WarmingPage } from "@/pages/warming";
import { ParsersPage } from "@/pages/parsers";
import { CommentingPage } from "@/pages/commenting";
import { ReactionsPage } from "@/pages/reactions";
import { AnalyticsPage } from "@/pages/analytics";

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
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
]);

import { z } from "zod";

export const analyticsSummarySchema = z.object({
  total_accounts: z.number(),
  active_accounts: z.number(),
  total_proxies: z.number(),
  warming_active: z.number(),
  parser_jobs: z.number(),
  commenting_campaigns: z.number(),
  reaction_campaigns: z.number(),
});

export type AnalyticsSummary = z.infer<typeof analyticsSummarySchema>;

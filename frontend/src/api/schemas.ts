import { z } from "zod";

// ---------- Analytics ----------

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

// ---------- Proxies ----------

export const proxyTypeSchema = z.enum(["socks5", "http", "mtproto"]);
export type ProxyType = z.infer<typeof proxyTypeSchema>;

export const proxyHealthSchema = z.enum(["unknown", "ok", "slow", "dead"]);
export type ProxyHealth = z.infer<typeof proxyHealthSchema>;

export const proxyOutSchema = z.object({
  id: z.number(),
  owner_id: z.number(),
  type: proxyTypeSchema,
  host: z.string(),
  port: z.number(),
  username: z.string().nullable(),
  has_password: z.boolean(),
  has_mtproto_secret: z.boolean(),
  health: proxyHealthSchema,
  last_checked_at: z.string().nullable(),
  latency_ms: z.number().nullable(),
  note: z.string().nullable(),
});
export type ProxyOut = z.infer<typeof proxyOutSchema>;

export const proxyListSchema = z.array(proxyOutSchema);

export const proxyHealthOutSchema = z.object({
  id: z.number(),
  health: proxyHealthSchema,
  latency_ms: z.number().nullable(),
  error: z.string().nullable().optional(),
});
export type ProxyHealthOut = z.infer<typeof proxyHealthOutSchema>;

// ---------- Accounts ----------

export const accountStatusSchema = z.enum([
  "new",
  "warming",
  "active",
  "flood",
  "spam_block",
  "banned",
  "retired",
]);
export type AccountStatus = z.infer<typeof accountStatusSchema>;

export const accountRoleSchema = z.enum([
  "commenter",
  "chatter",
  "reactor",
  "parser",
  "multi",
]);
export type AccountRole = z.infer<typeof accountRoleSchema>;

export const accountOutSchema = z.object({
  id: z.number(),
  owner_id: z.number(),
  proxy_id: z.number().nullable(),
  phone: z.string(),
  tg_user_id: z.number().nullable(),
  username: z.string().nullable(),
  first_name: z.string().nullable(),
  last_name: z.string().nullable(),
  api_id: z.number().nullable(),
  has_session: z.boolean(),
  status: accountStatusSchema,
  role: accountRoleSchema,
  trust_score: z.number(),
  last_active_at: z.string().nullable(),
  spam_block_until: z.string().nullable(),
  flood_until: z.string().nullable(),
  note: z.string().nullable(),
  is_enabled: z.boolean(),
});
export type AccountOut = z.infer<typeof accountOutSchema>;

export const accountListSchema = z.array(accountOutSchema);

export const loginStartOutSchema = z.object({
  login_token: z.string(),
  expires_at: z.string(),
});
export type LoginStartOut = z.infer<typeof loginStartOutSchema>;

export const loginCodeOutSchema = z.object({
  status: z.string(),
  account: accountOutSchema.nullable(),
});
export type LoginCodeOut = z.infer<typeof loginCodeOutSchema>;

export const loginPasswordOutSchema = z.object({
  status: z.string(),
  account: accountOutSchema,
});
export type LoginPasswordOut = z.infer<typeof loginPasswordOutSchema>;

export const healthCheckOutSchema = z.object({
  id: z.number(),
  status: accountStatusSchema,
  is_authorized: z.boolean(),
  error: z.string().nullable().optional(),
  tg_user_id: z.number().nullable().optional(),
  username: z.string().nullable().optional(),
});
export type HealthCheckOut = z.infer<typeof healthCheckOutSchema>;

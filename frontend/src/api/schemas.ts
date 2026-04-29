import { z } from "zod";

// ---------- Shared primitives ----------

export const statusCountSchema = z.object({
  status: z.string(),
  count: z.number(),
});
export type StatusCount = z.infer<typeof statusCountSchema>;

export const kindCountSchema = z.object({
  kind: z.string(),
  count: z.number(),
});
export type KindCount = z.infer<typeof kindCountSchema>;

export const kindStatusCountSchema = z.object({
  kind: z.string(),
  status: z.string(),
  count: z.number(),
});
export type KindStatusCount = z.infer<typeof kindStatusCountSchema>;

export const emojiStatusCountSchema = z.object({
  emoji: z.string(),
  status: z.string(),
  count: z.number(),
});
export type EmojiStatusCount = z.infer<typeof emojiStatusCountSchema>;

export const trustBucketSchema = z.object({
  bucket: z.string(),
  count: z.number(),
});
export type TrustBucket = z.infer<typeof trustBucketSchema>;

// ---------- Analytics (nested, mirrors sonya/combine/analytics/schemas.py) ----------

export const accountTopRowSchema = z.object({
  id: z.number(),
  phone: z.string(),
  username: z.string().nullable(),
  role: z.string(),
  status: z.string(),
  trust_score: z.number(),
});
export type AccountTopRow = z.infer<typeof accountTopRowSchema>;

export const commentingCampaignTopRowSchema = z.object({
  id: z.number(),
  name: z.string(),
  status: z.string(),
  posts_total: z.number(),
  comments_total: z.number(),
});
export type CommentingCampaignTopRow = z.infer<typeof commentingCampaignTopRowSchema>;

export const reactionCampaignTopRowSchema = z.object({
  id: z.number(),
  name: z.string(),
  status: z.string(),
  targets_total: z.number(),
  reactions_total: z.number(),
});
export type ReactionCampaignTopRow = z.infer<typeof reactionCampaignTopRowSchema>;

export const accountsSummarySchema = z.object({
  total: z.number(),
  by_status: z.array(statusCountSchema),
  avg_trust: z.number(),
  min_trust: z.number(),
  max_trust: z.number(),
  trust_buckets: z.array(trustBucketSchema),
  top: z.array(accountTopRowSchema),
  proxies_total: z.number(),
  proxies_by_health: z.array(statusCountSchema),
});
export type AccountsSummary = z.infer<typeof accountsSummarySchema>;

export const warmingSummarySchema = z.object({
  jobs_total: z.number(),
  jobs_by_status: z.array(statusCountSchema),
  actions_total: z.number(),
  actions_by_kind_status: z.array(kindStatusCountSchema),
});
export type WarmingSummary = z.infer<typeof warmingSummarySchema>;

export const parsersSummarySchema = z.object({
  jobs_total: z.number(),
  jobs_by_status: z.array(statusCountSchema),
  jobs_by_kind: z.array(kindCountSchema),
  results_total: z.number(),
  results_by_kind: z.array(kindCountSchema),
  results_by_job_kind: z.array(kindCountSchema),
});
export type ParsersSummary = z.infer<typeof parsersSummarySchema>;

export const commentingSummarySchema = z.object({
  campaigns_total: z.number(),
  campaigns_by_status: z.array(statusCountSchema),
  posts_total: z.number(),
  posts_by_status: z.array(statusCountSchema),
  comments_total: z.number(),
  comments_by_status: z.array(statusCountSchema),
  top: z.array(commentingCampaignTopRowSchema),
});
export type CommentingSummary = z.infer<typeof commentingSummarySchema>;

export const reactionsSummarySchema = z.object({
  campaigns_total: z.number(),
  campaigns_by_status: z.array(statusCountSchema),
  targets_total: z.number(),
  targets_by_status: z.array(statusCountSchema),
  reactions_total: z.number(),
  reactions_by_status: z.array(statusCountSchema),
  reactions_by_emoji_status: z.array(emojiStatusCountSchema),
  top: z.array(reactionCampaignTopRowSchema),
});
export type ReactionsSummary = z.infer<typeof reactionsSummarySchema>;

export const overallSummarySchema = z.object({
  accounts: accountsSummarySchema,
  warming: warmingSummarySchema,
  parsers: parsersSummarySchema,
  commenting: commentingSummarySchema,
  reactions: reactionsSummarySchema,
});
export type OverallSummary = z.infer<typeof overallSummarySchema>;

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

// ---------- Warming ----------

export const warmingJobStatusSchema = z.enum([
  "pending",
  "running",
  "paused",
  "completed",
  "cancelled",
]);
export type WarmingJobStatus = z.infer<typeof warmingJobStatusSchema>;

export const warmingActionKindSchema = z.enum([
  "subscribe_channel",
  "read_history",
  "react_post",
  "send_idle_message",
]);
export type WarmingActionKind = z.infer<typeof warmingActionKindSchema>;

export const warmingActionStatusSchema = z.enum([
  "pending",
  "done",
  "failed",
  "skipped",
]);
export type WarmingActionStatus = z.infer<typeof warmingActionStatusSchema>;

export const warmingActionOutSchema = z.object({
  id: z.number(),
  job_id: z.number(),
  kind: warmingActionKindSchema,
  target: z.string().nullable(),
  scheduled_at: z.string(),
  executed_at: z.string().nullable(),
  status: warmingActionStatusSchema,
  error: z.string().nullable(),
  trust_delta: z.number(),
});
export type WarmingActionOut = z.infer<typeof warmingActionOutSchema>;

export const warmingJobOutSchema = z.object({
  id: z.number(),
  owner_id: z.number(),
  account_id: z.number(),
  status: warmingJobStatusSchema,
  target_trust_score: z.number(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  last_action_at: z.string().nullable(),
  note: z.string().nullable(),
  total_actions: z.number(),
  actions_done: z.number(),
  actions_failed: z.number(),
  actions_pending: z.number(),
});
export type WarmingJobOut = z.infer<typeof warmingJobOutSchema>;

export const warmingJobListSchema = z.array(warmingJobOutSchema);

export const warmingJobDetailOutSchema = warmingJobOutSchema.extend({
  actions: z.array(warmingActionOutSchema),
});
export type WarmingJobDetailOut = z.infer<typeof warmingJobDetailOutSchema>;

// ---------- Parsers ----------

export const parserKindSchema = z.enum([
  "users_in_chat",
  "channels_of_user",
  "chat_history",
  "users_by_message",
]);
export type ParserKind = z.infer<typeof parserKindSchema>;

export const parserJobStatusSchema = z.enum([
  "pending",
  "running",
  "completed",
  "failed",
  "cancelled",
]);
export type ParserJobStatus = z.infer<typeof parserJobStatusSchema>;

export const parserResultKindSchema = z.enum(["user", "channel", "message"]);
export type ParserResultKind = z.infer<typeof parserResultKindSchema>;

export const parserJobOutSchema = z.object({
  id: z.number(),
  owner_id: z.number(),
  account_id: z.number(),
  kind: parserKindSchema,
  target: z.string(),
  status: parserJobStatusSchema,
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  error: z.string().nullable(),
  result_count: z.number(),
  note: z.string().nullable(),
});
export type ParserJobOut = z.infer<typeof parserJobOutSchema>;

export const parserJobListSchema = z.array(parserJobOutSchema);

export const parserResultOutSchema = z.object({
  id: z.number(),
  job_id: z.number(),
  kind: parserResultKindSchema,
  tg_id: z.number().nullable(),
  username: z.string().nullable(),
  title: z.string().nullable(),
  extra: z.record(z.string(), z.unknown()),
});
export type ParserResultOut = z.infer<typeof parserResultOutSchema>;

export const parserResultsPageSchema = z.object({
  items: z.array(parserResultOutSchema),
  total: z.number(),
  offset: z.number(),
  limit: z.number(),
});
export type ParserResultsPage = z.infer<typeof parserResultsPageSchema>;

// ---------- Commenting ----------

export const commentingCampaignStatusSchema = z.enum([
  "draft",
  "running",
  "paused",
  "archived",
]);
export type CommentingCampaignStatus = z.infer<typeof commentingCampaignStatusSchema>;

export const observedPostStatusSchema = z.enum([
  "new",
  "queued",
  "commented",
  "skipped",
]);
export type ObservedPostStatus = z.infer<typeof observedPostStatusSchema>;

export const commentStatusSchema = z.enum([
  "pending",
  "generated",
  "posted",
  "failed",
  "skipped",
]);
export type CommentStatus = z.infer<typeof commentStatusSchema>;

export const commentingCampaignOutSchema = z.object({
  id: z.number(),
  owner_id: z.number(),
  name: z.string(),
  status: commentingCampaignStatusSchema,
  target_channels: z.array(z.string()),
  account_ids: z.array(z.number()),
  prompt_template: z.string(),
  min_delay_seconds: z.number(),
  max_delay_seconds: z.number(),
  max_comments_per_day: z.number(),
  started_at: z.string().nullable(),
  paused_at: z.string().nullable(),
  archived_at: z.string().nullable(),
  note: z.string().nullable(),
});
export type CommentingCampaignOut = z.infer<typeof commentingCampaignOutSchema>;

export const commentingCampaignListSchema = z.array(commentingCampaignOutSchema);

export const observedPostOutSchema = z.object({
  id: z.number(),
  campaign_id: z.number(),
  channel: z.string(),
  tg_message_id: z.number(),
  text: z.string().nullable(),
  status: observedPostStatusSchema,
  observed_at: z.string(),
});
export type ObservedPostOut = z.infer<typeof observedPostOutSchema>;

export const plannedCommentOutSchema = z.object({
  id: z.number(),
  post_id: z.number(),
  account_id: z.number(),
  text: z.string().nullable(),
  status: commentStatusSchema,
  scheduled_at: z.string().nullable(),
  posted_at: z.string().nullable(),
  error: z.string().nullable(),
  tg_comment_id: z.number().nullable(),
});
export type PlannedCommentOut = z.infer<typeof plannedCommentOutSchema>;

// ---------- Reactions ----------

export const reactionCampaignStatusSchema = z.enum([
  "draft",
  "running",
  "paused",
  "archived",
]);
export type ReactionCampaignStatus = z.infer<typeof reactionCampaignStatusSchema>;

export const reactionTargetStatusSchema = z.enum([
  "pending",
  "planned",
  "done",
  "skipped",
]);
export type ReactionTargetStatus = z.infer<typeof reactionTargetStatusSchema>;

export const reactionStatusSchema = z.enum([
  "pending",
  "posted",
  "failed",
  "skipped",
]);
export type ReactionStatus = z.infer<typeof reactionStatusSchema>;

export const reactionCampaignOutSchema = z.object({
  id: z.number(),
  owner_id: z.number(),
  name: z.string(),
  status: reactionCampaignStatusSchema,
  target_channels: z.array(z.string()),
  account_ids: z.array(z.number()),
  emojis: z.array(z.string()),
  accounts_per_post: z.number(),
  max_reactions_per_day: z.number(),
  started_at: z.string().nullable(),
  paused_at: z.string().nullable(),
  archived_at: z.string().nullable(),
  note: z.string().nullable(),
});
export type ReactionCampaignOut = z.infer<typeof reactionCampaignOutSchema>;

export const reactionCampaignListSchema = z.array(reactionCampaignOutSchema);

export const reactionTargetOutSchema = z.object({
  id: z.number(),
  campaign_id: z.number(),
  channel: z.string(),
  tg_message_id: z.number(),
  status: reactionTargetStatusSchema,
  observed_at: z.string(),
});
export type ReactionTargetOut = z.infer<typeof reactionTargetOutSchema>;

export const reactionOutSchema = z.object({
  id: z.number(),
  target_id: z.number(),
  account_id: z.number(),
  emoji: z.string(),
  status: reactionStatusSchema,
  scheduled_at: z.string().nullable(),
  posted_at: z.string().nullable(),
  error: z.string().nullable(),
});
export type ReactionOut = z.infer<typeof reactionOutSchema>;

// ---------- Auth ----------

export const userRoleSchema = z.enum(["admin", "member"]);
export type UserRole = z.infer<typeof userRoleSchema>;

export const userOutSchema = z.object({
  id: z.number(),
  login: z.string(),
  owner_id: z.number(),
  role: z.string(),
  is_active: z.boolean(),
});
export type UserOut = z.infer<typeof userOutSchema>;

export const tokenOutSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
  expires_in: z.number(),
});
export type TokenOut = z.infer<typeof tokenOutSchema>;

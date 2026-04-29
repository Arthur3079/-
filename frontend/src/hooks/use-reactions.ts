import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import {
  apiFetch,
  reactionCampaignListSchema,
  reactionCampaignOutSchema,
  reactionTargetOutSchema,
  reactionOutSchema,
  type ReactionCampaignOut,
  type ReactionTargetOut,
  type ReactionOut,
} from "@/api";

const KEY = ["combine", "reactions"] as const;

export interface ReactionCampaignInput {
  name: string;
  target_channels?: string[];
  account_ids?: number[];
  emojis?: string[];
  accounts_per_post?: number;
  max_reactions_per_day?: number;
  note?: string | null;
}

export function useReactionCampaigns() {
  return useQuery<ReactionCampaignOut[]>({
    queryKey: KEY,
    queryFn: async () => {
      const raw = await apiFetch<unknown>("/combine/reactions/campaigns");
      return reactionCampaignListSchema.parse(raw);
    },
    staleTime: 30_000,
  });
}

export function useCreateReactionCampaign() {
  const qc = useQueryClient();
  return useMutation<ReactionCampaignOut, Error, ReactionCampaignInput>({
    mutationFn: async (input) => {
      const raw = await apiFetch<unknown>("/combine/reactions/campaigns", {
        method: "POST",
        body: input,
      });
      return reactionCampaignOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteReactionCampaign() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await apiFetch<void>(`/combine/reactions/campaigns/${id}`, {
        method: "DELETE",
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

const reactionTargetListSchema = z.array(reactionTargetOutSchema);
const reactionListSchema = z.array(reactionOutSchema);

export function useReactionTargets(campaignId: number | null) {
  return useQuery<ReactionTargetOut[]>({
    queryKey: ["combine", "reactions", "targets", campaignId],
    queryFn: async () => {
      const raw = await apiFetch<unknown>(
        `/combine/reactions/campaigns/${campaignId}/targets`,
      );
      return reactionTargetListSchema.parse(raw);
    },
    enabled: campaignId !== null,
    staleTime: 15_000,
  });
}

export function useTargetReactions(
  campaignId: number | null,
  targetId: number | null,
) {
  return useQuery<ReactionOut[]>({
    queryKey: ["combine", "reactions", "campaign", campaignId, "target", targetId, "reactions"],
    queryFn: async () => {
      const raw = await apiFetch<unknown>(
        `/combine/reactions/campaigns/${campaignId}/targets/${targetId}/reactions`,
      );
      return reactionListSchema.parse(raw);
    },
    enabled: campaignId !== null && targetId !== null,
    staleTime: 15_000,
  });
}

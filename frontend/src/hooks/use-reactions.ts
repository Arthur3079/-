import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiFetch,
  reactionCampaignOutSchema,
  reactionCampaignListSchema,
  type ReactionCampaignOut,
} from "@/api";

const KEY = ["combine", "reactions", "campaigns"] as const;

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
    staleTime: 15_000,
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

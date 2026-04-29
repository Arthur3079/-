import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiFetch,
  commentingCampaignOutSchema,
  commentingCampaignListSchema,
  type CommentingCampaignOut,
} from "@/api";

const KEY = ["combine", "commenting", "campaigns"] as const;

export interface CommentingCampaignInput {
  name: string;
  prompt_template: string;
  target_channels?: string[];
  account_ids?: number[];
  min_delay_seconds?: number;
  max_delay_seconds?: number;
  max_comments_per_day?: number;
  note?: string | null;
}

export function useCommentingCampaigns() {
  return useQuery<CommentingCampaignOut[]>({
    queryKey: KEY,
    queryFn: async () => {
      const raw = await apiFetch<unknown>("/combine/commenting/campaigns");
      return commentingCampaignListSchema.parse(raw);
    },
    staleTime: 15_000,
  });
}

export function useCreateCommentingCampaign() {
  const qc = useQueryClient();
  return useMutation<CommentingCampaignOut, Error, CommentingCampaignInput>({
    mutationFn: async (input) => {
      const raw = await apiFetch<unknown>("/combine/commenting/campaigns", {
        method: "POST",
        body: input,
      });
      return commentingCampaignOutSchema.parse(raw);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteCommentingCampaign() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await apiFetch<void>(`/combine/commenting/campaigns/${id}`, {
        method: "DELETE",
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

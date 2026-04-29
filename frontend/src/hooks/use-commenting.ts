import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import {
  apiFetch,
  commentingCampaignListSchema,
  commentingCampaignOutSchema,
  observedPostOutSchema,
  plannedCommentOutSchema,
  type CommentingCampaignOut,
  type ObservedPostOut,
  type PlannedCommentOut,
} from "@/api";

const KEY = ["combine", "commenting"] as const;

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
    staleTime: 30_000,
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

export function useUpdateCommentingCampaign() {
  const qc = useQueryClient();
  return useMutation<
    CommentingCampaignOut,
    Error,
    { id: number; patch: Partial<CommentingCampaignInput> }
  >({
    mutationFn: async ({ id, patch }) => {
      const raw = await apiFetch<unknown>(`/combine/commenting/campaigns/${id}`, {
        method: "PATCH",
        body: patch,
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

const observedPostListSchema = z.array(observedPostOutSchema);
const plannedCommentListSchema = z.array(plannedCommentOutSchema);

export function useCampaignPosts(campaignId: number | null) {
  return useQuery<ObservedPostOut[]>({
    queryKey: ["combine", "commenting", "posts", campaignId],
    queryFn: async () => {
      const raw = await apiFetch<unknown>(
        `/combine/commenting/campaigns/${campaignId}/posts`,
      );
      return observedPostListSchema.parse(raw);
    },
    enabled: campaignId !== null,
    staleTime: 15_000,
  });
}

export function usePostComments(
  campaignId: number | null,
  postId: number | null,
) {
  return useQuery<PlannedCommentOut[]>({
    queryKey: ["combine", "commenting", "campaign", campaignId, "post", postId, "comments"],
    queryFn: async () => {
      const raw = await apiFetch<unknown>(
        `/combine/commenting/campaigns/${campaignId}/posts/${postId}/comments`,
      );
      return plannedCommentListSchema.parse(raw);
    },
    enabled: campaignId !== null && postId !== null,
    staleTime: 15_000,
  });
}

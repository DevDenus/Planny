import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type AssistantCard } from "../../api/client";
import { ASSISTANT_KEY } from "../../api/queryClient";

const STATUS_KEY = [...ASSISTANT_KEY, "status"] as const;
const CHATS_KEY = [...ASSISTANT_KEY, "chats"] as const;
const chatKey = (id: string) => [...ASSISTANT_KEY, "chat", id] as const;
const chatPath = (id: string) => ({ params: { path: { chat_id: id } } });

const STATUS_STALE_MS = 5 * 60_000;

export function useAssistantStatus() {
  return useQuery({
    queryKey: STATUS_KEY,
    staleTime: STATUS_STALE_MS,
    queryFn: () => unwrap(api.GET("/api/v1/assistant/status")),
  });
}

export function useChats() {
  return useQuery({
    queryKey: CHATS_KEY,
    queryFn: async () => (await unwrap(api.GET("/api/v1/assistant/chats"))).items,
  });
}

export function useChat(id: string | undefined) {
  return useQuery({
    queryKey: chatKey(id ?? ""),
    enabled: id !== undefined,
    queryFn: () => unwrap(api.GET("/api/v1/assistant/chats/{chat_id}", chatPath(id as string))),
  });
}

export function useCreateChat() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => unwrap(api.POST("/api/v1/assistant/chats", { body: { text } })),
    onSuccess: (chat) => {
      client.setQueryData(chatKey(chat.id), chat);
      return client.invalidateQueries({ queryKey: CHATS_KEY });
    },
  });
}

export function useSendMessage(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ text, card }: { text: string; card?: AssistantCard | null }) =>
      unwrap(
        api.POST("/api/v1/assistant/chats/{chat_id}/messages", {
          ...chatPath(id),
          body: { text, ...(card && { card }) },
        }),
      ),
    onSuccess: (chat) => {
      client.setQueryData(chatKey(id), chat);
      return client.invalidateQueries({ queryKey: CHATS_KEY });
    },
    // A closed chat or a lost answer: what the server holds is the truth.
    onError: () => client.invalidateQueries({ queryKey: chatKey(id) }),
  });
}

export function useDeleteChat() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/v1/assistant/chats/{chat_id}", chatPath(id))),
    onSuccess: () => client.invalidateQueries({ queryKey: ASSISTANT_KEY }),
  });
}

/**
 * The recording goes as the body itself, with its own type. The audio is only in memory: it is
 * sent and dropped.
 */
export function transcribe(audio: Blob): Promise<string> {
  return unwrap(
    api.POST("/api/v1/assistant/transcribe", {
      // The body is raw audio: the typed body is a string, the serializer passes the blob as is.
      body: audio as unknown as string,
      bodySerializer: (body) => body,
      headers: { "Content-Type": audio.type || "audio/webm" },
    }),
  ).then((result) => result.text);
}

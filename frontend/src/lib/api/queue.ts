import { apiFetch } from "../apiClient";

export interface QueueRecipient {
  address: string;
  delay_reason: string | null;
}

export interface QueueEntry {
  queue_id: string;
  queue_name: string;
  arrival_time: string;
  message_size: number;
  sender: string;
  recipients: QueueRecipient[];
}

export function listQueue(): Promise<QueueEntry[]> {
  return apiFetch<QueueEntry[]>("/api/queue");
}

export function retryQueueMessage(queueId: string): Promise<void> {
  return apiFetch<void>(`/api/queue/${encodeURIComponent(queueId)}/retry`, { method: "POST" });
}

export function deleteQueueMessage(queueId: string): Promise<void> {
  return apiFetch<void>(`/api/queue/${encodeURIComponent(queueId)}`, { method: "DELETE" });
}

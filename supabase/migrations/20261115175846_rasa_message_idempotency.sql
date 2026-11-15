-- Idempotent delivery keys prevent duplicate RASA messages after network retries.
ALTER TABLE public.rasa_messages ADD COLUMN IF NOT EXISTS client_message_id uuid;
CREATE UNIQUE INDEX IF NOT EXISTS rasa_messages_client_message_id_uniq
  ON public.rasa_messages (conversation_id, sender_type, client_message_id)
  WHERE client_message_id IS NOT NULL;

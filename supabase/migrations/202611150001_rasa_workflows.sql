-- RASA migration: encrypted chat, access codes, moderator assignments, BK referrals and appointment workflow.
alter table public.bk_appointments drop constraint if exists bk_appointments_status_check;
alter table public.bk_appointments add constraint bk_appointments_status_check check(status=any(array['pending_review','awaiting_confirmation','confirmed','reschedule_requested','completed','cancelled']));
alter table public.bk_appointments add column if not exists scheduled_at timestamptz;
alter table public.bk_appointments add column if not exists counselor_note text;
alter table public.bk_appointments add column if not exists reviewed_at timestamptz;
alter table public.bk_appointments add column if not exists confirmed_at timestamptz;
alter table public.bk_appointments add column if not exists student_accepted boolean not null default false;
update public.bk_appointments set status='pending_review' where status='pending';
create table if not exists public.rasa_conversations(id uuid primary key default gen_random_uuid(),category text not null check(category in ('academic','family','friends','future','wellbeing','other')),status text not null default 'unassigned' check(status in ('unassigned','assigned','waiting_student','waiting_moderator','referred','closed')),assigned_moderator_id uuid references public.users(id) on delete set null,created_at timestamptz not null default now(),updated_at timestamptz not null default now(),last_message_at timestamptz not null default now());
create table if not exists public.rasa_messages(id uuid primary key default gen_random_uuid(),conversation_id uuid not null references public.rasa_conversations(id) on delete cascade,sender_type text not null check(sender_type in ('visitor','moderator')),sender_id uuid references public.users(id) on delete set null,encrypted_payload text not null,nonce text not null,auth_tag text not null,created_at timestamptz not null default now(),read_at timestamptz);
create index if not exists rasa_messages_conversation_created_idx on public.rasa_messages(conversation_id,created_at);
create table if not exists public.rasa_access_codes(conversation_id uuid primary key references public.rasa_conversations(id) on delete cascade,code_hash text not null unique,expires_at timestamptz not null default(now()+interval '30 days'),created_at timestamptz not null default now());
create index if not exists rasa_conversations_queue_idx on public.rasa_conversations(status,last_message_at desc);
create table if not exists public.rasa_typing_presence(conversation_id uuid not null references public.rasa_conversations(id) on delete cascade,actor_type text not null check(actor_type in ('visitor','moderator')),actor_key text not null,is_typing boolean not null default false,updated_at timestamptz not null default now(),primary key(conversation_id,actor_type,actor_key));
create table if not exists public.rasa_referrals(id uuid primary key default gen_random_uuid(),conversation_id uuid not null references public.rasa_conversations(id) on delete cascade,moderator_id uuid not null references public.users(id),summary text not null check(length(summary) between 10 and 1200),consent boolean not null default false,urgent boolean not null default false,status text not null default 'pending' check(status in ('pending','accepted','closed')),created_at timestamptz not null default now());
alter table public.rasa_conversations enable row level security; alter table public.rasa_messages enable row level security; alter table public.rasa_access_codes enable row level security; alter table public.rasa_referrals enable row level security; alter table public.rasa_typing_presence enable row level security;
revoke all on public.rasa_conversations,public.rasa_messages,public.rasa_access_codes,public.rasa_referrals,public.rasa_typing_presence from anon,authenticated;
create table if not exists public.rasa_bk_requests(
 id uuid primary key default gen_random_uuid(),
 school_id uuid not null references public.schools(id) on delete cascade,
 code_hash text not null unique,
 requested_at timestamptz not null,
 mode text not null check(mode in ('in_person','online')),
 encrypted_payload text not null,
 nonce text not null,
 auth_tag text not null,
 status text not null default 'pending_review' check(status in ('pending_review','awaiting_confirmation','reschedule_requested','confirmed','completed','cancelled')),
 scheduled_at timestamptz,
 counselor_id uuid references public.users(id) on delete set null,
 counselor_note text,
 student_accepted boolean not null default false,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 reviewed_at timestamptz,
 confirmed_at timestamptz,
 expires_at timestamptz not null default(now()+interval '30 days')
);
create index if not exists rasa_bk_requests_school_queue_idx on public.rasa_bk_requests(school_id,status,created_at);
alter table public.rasa_bk_requests enable row level security;
revoke all on public.rasa_bk_requests from anon,authenticated;

alter table public.rasa_conversations add column if not exists school_id uuid references public.schools(id) on delete set null;
alter table public.rasa_referrals add column if not exists school_id uuid references public.schools(id) on delete set null;
update public.rasa_conversations c set school_id=(select id from public.schools where status='active' order by name limit 1)
where c.school_id is null and (select count(*) from public.schools where status='active')=1;
update public.rasa_referrals r set school_id=c.school_id from public.rasa_conversations c
where r.conversation_id=c.id and r.school_id is null;
create index if not exists rasa_conversations_school_idx on public.rasa_conversations(school_id,status,last_message_at desc);
create index if not exists rasa_referrals_school_idx on public.rasa_referrals(school_id,status,created_at);

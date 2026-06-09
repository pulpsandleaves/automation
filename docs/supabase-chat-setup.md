# Supabase Human Chat Setup

Use Supabase for the live human chat inbox. Google Sheets remains the enquiry summary and order/reporting layer.

## 1. Create The Tables

Open the Supabase SQL editor and run:

```sql
create extension if not exists pgcrypto;

create table if not exists public.whatsapp_contacts (
  phone_number text primary key,
  profile_name text default '',
  first_message_at timestamptz,
  first_enquiry_text text default '',
  last_message_at timestamptz,
  last_message_direction text default '',
  message_count integer not null default 0,
  last_message_text text default '',
  last_message_type text default '',
  last_message_id text default '',
  conversation_gist text default '',
  enquiry_status text not null default 'open',
  source text default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.whatsapp_messages (
  id uuid primary key default gen_random_uuid(),
  phone_number text not null references public.whatsapp_contacts(phone_number) on delete cascade,
  direction text not null,
  message_type text not null default 'text',
  message_text text default '',
  message_id text default '',
  status text default '',
  agent text default '',
  template_name text default '',
  source text default '',
  media_id text default '',
  media_mime_type text default '',
  media_filename text default '',
  error text default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists whatsapp_contacts_last_message_at_idx
  on public.whatsapp_contacts (last_message_at desc);

create index if not exists whatsapp_messages_phone_created_at_idx
  on public.whatsapp_messages (phone_number, created_at desc);

create unique index if not exists whatsapp_messages_message_id_unique_idx
  on public.whatsapp_messages (message_id)
  where message_id is not null and message_id <> '';
```

## 2. Configure Render

Set these environment variables:

```text
SUPABASE_CHAT_ENABLED=true
SUPABASE_URL=https://hotvabriczbokrcpvmzo.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
SUPABASE_CONTACTS_TABLE=whatsapp_contacts
SUPABASE_MESSAGES_TABLE=whatsapp_messages
SUPABASE_CHAT_CONTACT_CACHE_SECONDS=5
SUPABASE_CHAT_MESSAGE_CACHE_SECONDS=3
```

Keep `SUPABASE_SERVICE_ROLE_KEY` server-only. Do not put it in browser JavaScript or public frontend config.

## 3. What Gets Stored Where

- Supabase `whatsapp_messages`: full inbound and outbound human chat history.
- Supabase `whatsapp_contacts`: fast inbox list, latest message, message count, and conversation gist.
- Google Sheets `WhatsApp Contacts`: one row per customer with first enquiry, latest message, gist, and enquiry status.
- Google order sheets: unchanged; website and WhatsApp Flow orders still use the existing order pipeline.

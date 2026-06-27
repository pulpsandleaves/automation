# Pulps & Leaves WhatsApp Order Automation

Beginner-friendly Flask system for the Pulps & Leaves premium makhana order flow.

## What It Does

1. Customer submits a makhana order on the website or WhatsApp Flow.
2. Flask validates the order and stores a backup in SQLite.
3. The order is written to today's Google Sheet tab, for example `orders 2026-05-14`.
4. WhatsApp automation sends editable customer-service messages such as order received, tracking, and support replies.
5. Approved templates are only used from the operator/template panel or enabled confirmation flows.
6. Admin receives a WhatsApp alert.
7. Incoming WhatsApp contacts are saved to a permanent Google Sheet summary tab.
8. Optional Supabase chat storage powers the live human chat inbox.
9. WhatsApp status and order status are saved for dashboard visibility.

## Main URLs

- `GET /` - protected WhatsApp chat operator panel.
- `GET /admin/chat?token=<ADMIN_DASHBOARD_TOKEN>` - protected WhatsApp chat operator panel.
- `GET /checkout` - optional mobile-first checkout page.
- `POST /checkout` - checkout form submit.
- `POST /api/orders` - JSON order API.
- `POST /api/orders/confirm-latest` - reads latest Google Sheet row and sends confirmation when confirmations are enabled.
- `GET /admin?token=<ADMIN_DASHBOARD_TOKEN>` - admin dashboard.
- `POST /admin/send-template` - admin form for bulk approved WhatsApp template sends.
- `POST /api/admin/template-messages` - JSON API for bulk approved WhatsApp template sends.
- `GET /webhook` and `POST /webhook` - Meta WhatsApp webhook.

## Google Sheet Columns

The app creates a fresh daily tab automatically using `GOOGLE_DAILY_WORKSHEET_PREFIX` and the local date, for example `orders 2026-05-14`.

Create the first tab manually only if you want to pre-format it. Otherwise the app will create the tab and add these columns:

| Order ID | Customer Name | Phone Number | Product Name | Quantity | Price | Total Amount | Delivery Address | Payment Method | Order Status | Timestamp |
|---|---|---|---|---|---|---|---|---|---|---|

The app will automatically add these system columns:

| WhatsApp Message ID | WhatsApp Status | WhatsApp Sent At | WhatsApp Error |
|---|---|---|---|

The webhook also creates or updates a `WhatsApp Contacts` tab as a one-row-per-customer enquiry summary:

| Phone Number | Profile Name | First Message At | First Enquiry Text | Last Message At | Last Message Direction | Message Count | Last Message Text | Last Message Type | Last Message ID | Conversation Gist | Enquiry Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|

If Supabase chat is disabled, inbound and outbound chat messages continue to be saved to a `WhatsApp Conversations` tab as the fallback history:

| Timestamp | Phone Number | Direction | Message Type | Message Text | Message ID | Status | Agent | Template Name | Source |
|---|---|---|---|---|---|---|---|---|---|

## Supabase Human Chat

Set `SUPABASE_CHAT_ENABLED=true`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` to use Supabase as the fast live chat store. The admin chat APIs then read contacts and messages from Supabase; Google Sheets still receives the customer enquiry summary.

See [Supabase chat setup](docs/supabase-chat-setup.md) for the copy-paste SQL schema and Render environment variables.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open `http://localhost:5000/?token=YOUR_TOKEN`.

If `ADMIN_DASHBOARD_TOKEN` is set, open `http://localhost:5000/admin/chat?token=YOUR_TOKEN`.

The operator panel shows recent WhatsApp contacts, saved conversation history, a reply box for open 24-hour chats, and a compact approved-template sender. When Supabase chat is enabled, this panel reads live chat data from Supabase instead of scanning Google Sheets.

## JSON Order API Example

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:5000/api/orders" `
  -ContentType "application/json" `
  -Body '{
    "customer_name": "Atharv",
    "phone_number": "9835496666",
    "product_name": "Premium Makhana",
    "quantity": 1,
    "price": 999,
    "total_amount": 999,
    "delivery_address": "Whitefield, Bangalore",
    "payment_method": "Online Payment",
    "order_status": "Order Received"
  }'
```

## Notes

- Google Sheets is the live order database and customer enquiry summary.
- Supabase is optional and is used for faster human chat contacts/messages.
- SQLite is a local backup and dashboard source.
- `ORDER_CONFIRMATIONS_ENABLED=false` keeps automatic confirmation templates paused until an approved makhana template is ready.
- WhatsApp template messages are recommended for production business-initiated confirmations.

## Guides

- [Google Sheets setup](docs/google-sheets-setup.md)
- [Supabase chat setup](docs/supabase-chat-setup.md)
- [WhatsApp API setup](docs/whatsapp-api-setup.md)
- [WhatsApp Flow setup](docs/whatsapp-flow-setup.md)
- [Example sheet format](docs/example-google-sheet-format.md)

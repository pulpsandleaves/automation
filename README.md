# Pulps & Leaves WhatsApp Order Confirmation System

Beginner-friendly Flask system for a premium mango ecommerce flow.

## What It Does

1. Customer places an order on the website checkout.
2. Flask validates the order and stores a backup in SQLite.
3. Order is written to today's Google Sheet tab, for example `orders 2026-05-14`.
4. Flask reads the newest order row from Google Sheets.
5. WhatsApp Cloud API sends the customer confirmation message.
6. Admin receives a WhatsApp alert.
7. Incoming WhatsApp contacts are saved to a permanent Google Sheet tab.
8. WhatsApp status and order status are saved for dashboard visibility.

## Main URLs

- `GET /` - protected WhatsApp chat operator panel.
- `GET /admin/chat?token=<ADMIN_DASHBOARD_TOKEN>` - protected WhatsApp chat operator panel.
- `GET /checkout` - optional mobile-first checkout page.
- `POST /checkout` - checkout form submit.
- `POST /api/orders` - JSON order API.
- `POST /api/orders/confirm-latest` - reads latest Google Sheet row and sends confirmation.
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

The webhook also creates or updates a `WhatsApp Contacts` tab for inbound chat contacts:

| Phone Number | Profile Name | First Message At | Last Message At | Message Count | Last Message Text | Last Message Type | Last Message ID | Source |
|---|---|---|---|---|---|---|---|---|

Inbound and outbound chat messages are saved to a `WhatsApp Conversations` tab:

| Timestamp | Phone Number | Direction | Message Type | Message Text | Message ID | Status | Agent | Template Name | Source |
|---|---|---|---|---|---|---|---|---|---|

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

The operator panel shows recent WhatsApp contacts, saved conversation history, a reply box for open 24-hour chats, and a compact approved-template sender.

## JSON Order API Example

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:5000/api/orders" `
  -ContentType "application/json" `
  -Body '{
    "customer_name": "Atharv",
    "phone_number": "9835496666",
    "product_name": "Premium Malda Mangoes",
    "quantity": 1,
    "price": 999,
    "total_amount": 999,
    "delivery_address": "Whitefield, Bangalore",
    "payment_method": "Online Payment",
    "order_status": "Confirmed"
  }'
```

## Notes

- Google Sheets is the live order database.
- SQLite is a local backup and dashboard source.
- WhatsApp template messages are recommended for production business-initiated confirmations.
- If `ORDER_CONFIRMATION_TEMPLATE_NAME` is empty, the app sends a normal text message, which only works when WhatsApp allows that conversation window.

## Guides

- [Google Sheets setup](docs/google-sheets-setup.md)
- [WhatsApp API setup](docs/whatsapp-api-setup.md)
- [Example sheet format](docs/example-google-sheet-format.md)

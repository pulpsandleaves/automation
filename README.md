# Pulps & Leaves WhatsApp Order Confirmation System

Beginner-friendly Flask system for a premium mango ecommerce flow.

## What It Does

1. Customer places an order on the website checkout.
2. Flask validates the order and stores a backup in SQLite.
3. Order is written to Google Sheets.
4. Flask reads the newest order row from Google Sheets.
5. WhatsApp Cloud API sends the customer confirmation message.
6. Admin receives a WhatsApp alert.
7. WhatsApp status and order status are saved for dashboard visibility.

## Main URLs

- `GET /checkout` - mobile-first checkout page.
- `POST /checkout` - checkout form submit.
- `POST /api/orders` - JSON order API.
- `POST /api/orders/confirm-latest` - reads latest Google Sheet row and sends confirmation.
- `GET /admin?token=<ADMIN_DASHBOARD_TOKEN>` - admin dashboard.
- `GET /webhook` and `POST /webhook` - Meta WhatsApp webhook.

## Google Sheet Columns

Create a sheet tab named `Orders` with these columns:

| Order ID | Customer Name | Phone Number | Product Name | Quantity | Price | Total Amount | Delivery Address | Payment Method | Order Status | Timestamp |
|---|---|---|---|---|---|---|---|---|---|---|

The app will automatically add these system columns:

| WhatsApp Message ID | WhatsApp Status | WhatsApp Sent At | WhatsApp Error |
|---|---|---|---|

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open `http://localhost:5000/checkout`.

If `ADMIN_DASHBOARD_TOKEN` is set, open `http://localhost:5000/admin?token=YOUR_TOKEN`.

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

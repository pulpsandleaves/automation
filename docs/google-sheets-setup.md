# Google Sheets Setup Guide

1. Create or open the Google Sheet for Pulps & Leaves orders.
2. Create a tab named `Orders`.
3. Add this header row:

```text
Order ID | Customer Name | Phone Number | Product Name | Quantity | Price | Total Amount | Delivery Address | Payment Method | Order Status | Timestamp
```

4. In Google Cloud Console, create a Service Account.
5. Download the service account JSON key.
6. Share the Google Sheet with the service account email as `Editor`.
7. Set one of these in `.env`:

```text
GOOGLE_SHEET_ID=your_google_sheet_id
GOOGLE_CREDENTIALS_JSON={...full service account json...}
```

Or keep `google_credentials.json` locally and set:

```text
GOOGLE_CREDENTIALS_FILE=google_credentials.json
```

The app automatically adds:

```text
WhatsApp Message ID | WhatsApp Status | WhatsApp Sent At | WhatsApp Error
```


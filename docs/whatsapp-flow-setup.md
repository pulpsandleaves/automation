# WhatsApp Flow Setup

The mini-app Flow JSON is in:

```text
whatsapp_mango_order_flow.json
```

## Upload The Flow

1. Open Meta Business Suite or WhatsApp Manager.
2. Go to WhatsApp Manager > Flows.
3. Create a new Flow.
4. Open the JSON editor.
5. Paste the contents of `whatsapp_mango_order_flow.json`.
6. Preview the Flow and fix any Meta validation warnings.
7. Publish the Flow.

## Images

The Flow uses public images from the Render server:

```text
https://pulps-and-leaves-whatsapp-automation.onrender.com/assets/main.png
https://pulps-and-leaves-whatsapp-automation.onrender.com/assets/welcome_template.png
https://pulps-and-leaves-whatsapp-automation.onrender.com/assets/order_delivered_header.png
```

The Flask app exposes these via:

```text
/assets/<filename>
```

If your live Render URL is different, replace the three image URLs in the Flow JSON before publishing.

## What Happens After Submit

When the customer submits the Flow, WhatsApp sends an `nfm_reply` webhook. The server reads:

```text
flow_name
city
box_combo
customer_name
mobile_number
delivery_address
payment_method
```

Then it creates the order through the existing order system, saves it to Google Sheets, and sends the normal WhatsApp confirmation.

# WhatsApp Cloud API Setup Guide

1. Open Meta for Developers.
2. Select the Pulps & Leaves app.
3. Go to WhatsApp > API setup.
4. Copy:

```text
WHATSAPP_ACCESS_TOKEN
WHATSAPP_PHONE_NUMBER_ID
```

5. Add the webhook callback URL:

```text
https://pulps-and-leaves-whatsapp-automation.onrender.com/webhook
```

6. Use your verify token:

```text
WHATSAPP_VERIFY_TOKEN=pulps-leaves-test-123
```

7. Subscribe to:

```text
messages
```

8. For reliable production order confirmations, create a Utility template similar to:

```text
Hello {{1}} 👋

Thank you for ordering from Pulps & Leaves 🥭

Your order has been confirmed successfully.

Order ID: {{2}}

Items:
{{3}}

Quantity: {{4}}

Total Amount: {{5}}

Delivery Address:
{{6}}

Order Status:
{{7}}

We’ll contact you shortly regarding delivery.

For support, reply to this message.
```

9. After Meta approves the template, set:

```text
ORDER_CONFIRMATION_TEMPLATE_NAME=your_template_name
ORDER_CONFIRMATION_TEMPLATE_LANGUAGE=en_US
```


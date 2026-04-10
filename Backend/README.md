---
title: Godmod Backend
emoji: 🚀
colorFrom: blue
colorTo: purple
sdk: docker
---

# Godmod Backend

Application backend pour Godmod avec API et monitoring.

## Admin API security

All protected write routes require the `X-Admin-Key` header.

Example:

```bash
curl -X POST http://127.0.0.1:8000/settings/ai \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your-admin-secret" \
  -d "{\"enabled\": false}"
```

Set `ADMIN_SECRET_KEY` in `.env` or protected write routes will return `503`.

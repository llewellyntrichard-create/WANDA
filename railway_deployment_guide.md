# Project Wanda 2 — Railway Production Deployment Guide

This guide provides step-by-step instructions for deploying **Wanda 2** (`wanda2-v2.py`) to Railway with persistent SQLite storage, webhook integrations, and automated background task execution.

---

## 📋 Included Deployment Files

| File | Purpose |
| :--- | :--- |
| **`Dockerfile`** | Container definition using Python 3.12-slim, system dependencies, and Litestream. |
| **`Procfile`** | Web server execution command for Railway (`uvicorn wanda2-v2:app`). |
| **`railway.json`** | Railway infrastructure config (enforces single replica `numReplicas: 1`). |
| **`requirements.txt`** | Python library dependencies (`fastapi`, `httpx`, `google-genai`, `apscheduler`, etc.). |
| **`entrypoint.sh`** | Startup script handling data directory setup, optional Litestream restore, and Uvicorn launch. |
| **`.env.example`** | Environment variable template for API keys, database paths, and secrets. |

---

## 🚀 Step-by-Step Deployment Instructions

### Step 1: Create a Railway Project
1. Log into your [Railway Console](https://railway.app/).
2. Click **+ New Project** -> **Deploy from GitHub repo**.
3. Select the repository containing your `wanda2-v2.py` and deployment files.

---

### Step 2: Attach a Persistent Volume (Critical for SQLite)
* **Why this matters:** Railway container filesystems are ephemeral. Without a volume, database restarts will wipe all customer appointments, billing records, and token usage logs.
1. In your Railway service canvas, click **+ New** -> **Volume**.
2. Mount the volume to your service container at the mount path:
   ```text
   /app/data
   ```
3. Set the environment variable:
   ```env
   MONOLOG_DB_FILE=/app/data/wanda2.db
   ```

---

### Step 3: Configure Environment Variables
In Railway, navigate to **Variables** and add the following keys:

```env
# Server Networking
PORT=8000
ENVIRONMENT=production

# Database Path
MONOLOG_DB_FILE=/app/data/wanda2.db

# Google Gemini API
GEMINI_API_KEY=your_gemini_api_key

# Meta WhatsApp Cloud API
META_APP_SECRET=your_meta_app_secret
VERIFY_TOKEN=your_meta_webhook_verify_token
PHONE_NUMBER_ID=your_whatsapp_phone_number_id
WHATSAPP_TOKEN=your_whatsapp_access_token

# Yoco Payment Gateway
YOCO_SECRET_KEY=sk_live_your_yoco_secret_key
YOCO_WEBHOOK_SECRET=secret_your_yoco_webhook_secret
```

---

### Step 4: Enforce Single Replica Execution (Prevent Duplicate Cron Alerts)
* **Why this matters:** Wanda 2 runs an internal `apscheduler` loop for 09:00 SAST morning briefings and hourly 24h customer reminders. Multiple instances will send duplicate WhatsApp messages to clients.
1. Go to **Settings > Scaling**.
2. Set **Instance Count / Replicas** strictly to **`1`**.
3. Disable horizontal autoscaling.

---

### Step 5: Configure Webhook Endpoint URLs

Once your deployment is live, Railway will assign a public domain (e.g., `https://wanda2-production.up.railway.app`).

#### 1. Meta WhatsApp Webhook Setup
* **Callback URL:** `https://wanda2-production.up.railway.app/webhook`
* **Verify Token:** Must match `VERIFY_TOKEN` in your environment.
* **Subscribed Fields:** `messages`.

#### 2. Yoco Payment Webhook Setup
* **Webhook URL:** `https://wanda2-production.up.railway.app/api/webhooks/yoco`
* **Subscribed Events:** `payment.succeeded`, `payment.failed`.

---

## 🔍 Verification & Diagnostic Testing

Once deployed, test your service:

1. **Health Check:**
   ```bash
   curl -i https://wanda2-production.up.railway.app/
   ```
   Should return `HTTP 200 OK` with `{"status": "Wanda 2 Active"}`.

2. **Self-Service Onboarding Endpoint:**
   ```bash
   curl -X POST https://wanda2-production.up.railway.app/api/onboard \
     -H "Content-Type: application/json" \
     -d '{
       "business_name": "Test Plumbing Co",
       "owner_phone": "27821234567",
       "whatsapp_number": "27829990000"
     }'
   ```

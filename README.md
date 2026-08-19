# MongoDB Free Cluster Keep-Alive Automation 🚀

[![MongoDB Keep-Alive](https://github.com/mian196/mongodb-cluster-automation/actions/workflows/mongodb-keepalive.yml/badge.svg)](https.github.com/mian196/mongodb-cluster-automation/actions/workflows/mongodb-keepalive.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An automated Python tool and GitHub Actions workflow designed to prevent **MongoDB Atlas Free Tier (M0) clusters** from being paused or taken down due to inactivity.

MongoDB Atlas automatically pauses free tier clusters if no read/write operations occur for 60 consecutive days. This automation connects to your MongoDB cluster(s) at the **start of every month**, creates/updates a lightweight test collection with dummy data, and alerts you via **Discord Webhooks** on success or failure.

---

## ✨ Features

- 🔄 **Prevent Cluster Deactivation:** Sends actual write & read operations (`ping`, `upsert`, `find`) to keep clusters active.
- 🌐 **Multi-Cluster Support:** Ping multiple MongoDB clusters in a single workflow run.
- 🔒 **Credential Security & URI Masking:** All URIs are sanitized and masked in console logs and Discord notifications to prevent exposing passwords.
- ⏰ **Automated Monthly Schedule:** GitHub Action runs automatically on the **1st of every month at 00:00 UTC**.
- 🔘 **Manual Execution:** Includes `workflow_dispatch` trigger so you can test or run it anytime on demand from the GitHub UI.
- 📢 **Rich Discord Notifications:** Formatted embed notifications sent directly to your Discord channel showing status, latency, total pings, and error messages.
- 🧪 **Flexible URI Formats:** Accepts comma-separated, newline-separated, JSON arrays, or individual cluster environment variables.

---

## 🛠️ GitHub Repository Secrets Setup

To run this automation via GitHub Actions, add your connection details as **Repository Secrets**:

### 1. Open GitHub Repository Secrets
1. Go to your GitHub repository.
2. Click **Settings** > **Secrets and variables** > **Actions**.
3. Click **New repository secret**.

### 2. Add Secrets

| Secret Name | Required | Description & Example |
| :--- | :---: | :--- |
| `MONGODB_URIS` | **Yes** | MongoDB connection string(s). Supports multiple formats (see below). |
| `DISCORD_WEBHOOK_URL` | Optional | Discord Webhook URL for success/failure notifications. |
| `MONGODB_DB_NAME` | Optional | Custom database name (default: `keepalive_db`). |
| `MONGODB_COLLECTION_NAME` | Optional | Custom collection name (default: `keepalive_status`). |

---

### 💡 Multi-URI Configuration Formats

You can supply single or multiple MongoDB URIs in `MONGODB_URIS` using any of the following formats:

#### Option A: Comma-Separated String
```env
mongodb+srv://user1:pass1@cluster0.abcde.mongodb.net/?retryWrites=true&w=majority,mongodb+srv://user2:pass2@cluster1.fghij.mongodb.net/?retryWrites=true&w=majority
```

#### Option B: Newline-Separated List
```env
mongodb+srv://user1:pass1@cluster0.abcde.mongodb.net/?retryWrites=true&w=majority
mongodb+srv://user2:pass2@cluster1.fghij.mongodb.net/?retryWrites=true&w=majority
```

#### Option C: JSON Array with Custom Labels
```json
[
  { "name": "Production Cluster", "uri": "mongodb+srv://user1:pass1@cluster0.abcde.mongodb.net" },
  { "name": "Staging Cluster", "uri": "mongodb+srv://user2:pass2@cluster1.fghij.mongodb.net" }
]
```

#### Option D: Individual Secrets
You can also set individual secrets like `MONGODB_URI_PROD` and `MONGODB_URI_DEV` or `MONGODB_URI`. The tool automatically scans and detects all environment variables starting with `MONGODB_URI`.

---

## 🔔 Discord Webhook Setup

1. Open your Discord Server settings.
2. Go to **Integrations** > **Webhooks** > **New Webhook**.
3. Choose the channel where you want to receive keep-alive reports.
4. Copy the Webhook URL and paste it into the `DISCORD_WEBHOOK_URL` GitHub Secret.

### Example Discord Notification
![Discord Notification Preview](assets/discord-notification-preview.png)

When the workflow executes, Discord receives a detailed summary:
- **Green Embed:** All clusters healthy and updated.
- **Red Embed:** Connection error or failed ping with detailed stack trace/message.

---

## ⚙️ How the Workflow Works

The workflow file is located at [.github/workflows/mongodb-keepalive.yml](file://.github/workflows/mongodb-keepalive.yml).

- **Schedule:** Triggers via CRON `0 0 1 * *` (1st day of every month).
- **Manual Trigger:** Go to **Actions** tab > **MongoDB Free Cluster Keep-Alive** > **Run workflow**.

---

## 💻 Local Installation & Usage

You can also run the keep-alive script locally on your machine.

### 1. Clone Repository & Install Dependencies
```bash
git clone https://github.com/mian196/mongodb-cluster-automation.git
cd mongodb-cluster-automation

# Create virtual environment (optional)
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` and fill in your `MONGODB_URIS` and `DISCORD_WEBHOOK_URL`.

### 3. Run the Keep-Alive Script
```bash
python keepalive.py
```

### 4. Run Unit Tests
```bash
python -m unittest discover -s tests
```

---

## 📁 Database Activity Details

When the script connects to your cluster, it performs the following operations:

1. **Admin Ping:** Issues `admin.command('ping')` to test network latency and server responsiveness.
2. **Database & Collection Access:** Accesses database `keepalive_db` and collection `keepalive_status`.
3. **Document Upsert:** Updates a document with `_id: "keepalive_ping_record"` setting:
   - `last_ping_utc`: Current timestamp in ISO format.
   - `status`: `"active"`
   - `total_pings`: Incremented count of total executions (`$inc: 1`).
   - `dummy_payload`: A unique random token hash to ensure genuine write operations.
4. **Verification:** Reads back the document to confirm transaction success.

---

## 🛡️ License

Distributed under the [MIT License](LICENSE).
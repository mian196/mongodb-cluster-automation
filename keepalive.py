#!/usr/bin/env python3
"""
MongoDB Free Cluster Keep-Alive Automation Tool.

Connects to one or multiple MongoDB Atlas free clusters, creates/updates a test
collection with dummy data to simulate activity, and prevents clusters from being paused
due to inactivity. Sends notifications to a Discord Webhook.
"""

import json
import logging
import os
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import requests
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import pymongo
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
except ImportError:
    pymongo = None
    MongoClient = None
    PyMongoError = Exception

# Configure stdout encoding on Windows if needed
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("mongodb-keepalive")


def mask_uri(uri: str) -> str:
    """
    Mask password and sensitive info in MongoDB URI for safe logging.
    Example: mongodb+srv://user:secret123@cluster.mongodb.net/ -> mongodb+srv://us***:****@cluster.mongodb.net/
    """
    if not uri or not isinstance(uri, str):
        return "<invalid-uri>"

    try:
        if "://" in uri:
            scheme, rest = uri.split("://", 1)
            if "@" in rest:
                user_info, host_info = rest.rsplit("@", 1)
                if ":" in user_info:
                    user, _ = user_info.split(":", 1)
                    masked_user = user[:2] + "***" if len(user) > 2 else "***"
                    return f"{scheme}://{masked_user}:****@{host_info}"
                else:
                    return f"{scheme}://****@{host_info}"
            return f"{scheme}://{rest}"
    except Exception:
        pass

    return uri[:12] + "..." + uri[-12:] if len(uri) > 24 else "****"


def parse_mongodb_uris() -> List[Dict[str, str]]:
    """
    Parse MongoDB URIs from environment variables.
    Supports:
    1. MONGODB_URIS (comma-separated, newline-separated, or JSON string array / object list)
    2. MONGODB_URI or MONGODB_URI_* (individual environment variables)
    
    Returns a list of dicts: [{"name": label, "uri": connection_string}]
    """
    clusters: List[Dict[str, str]] = []
    seen_uris = set()

    # 1. Parse MONGODB_URIS
    raw_uris = os.getenv("MONGODB_URIS", "").strip()
    if raw_uris:
        # Check if JSON format
        if raw_uris.startswith("[") and raw_uris.endswith("]"):
            try:
                parsed_json = json.loads(raw_uris)
                for item in parsed_json:
                    if isinstance(item, str) and item.strip():
                        u = item.strip()
                        if u not in seen_uris:
                            seen_uris.add(u)
                            clusters.append({"name": f"Cluster-{len(clusters)+1}", "uri": u})
                    elif isinstance(item, dict) and "uri" in item:
                        u = item["uri"].strip()
                        name = item.get("name", f"Cluster-{len(clusters)+1}")
                        if u and u not in seen_uris:
                            seen_uris.add(u)
                            clusters.append({"name": name, "uri": u})
            except json.JSONDecodeError:
                logger.warning("MONGODB_URIS appeared to be JSON but failed parsing. Fallback to delimiter split.")

        if not clusters:
            # Split by newline or comma or semicolon
            delimiters = r"[\n,;]+"
            parts = [p.strip() for p in re.split(delimiters, raw_uris) if p.strip()]
            for idx, p in enumerate(parts, 1):
                # Handle possible "Name=URI" format
                if "=" in p and (p.startswith("mongodb://") or p.startswith("mongodb+srv://")) is False:
                    name_part, uri_part = p.split("=", 1)
                    uri_clean = uri_part.strip()
                    if uri_clean and uri_clean not in seen_uris:
                        seen_uris.add(uri_clean)
                        clusters.append({"name": name_part.strip(), "uri": uri_clean})
                else:
                    if p not in seen_uris:
                        seen_uris.add(p)
                        clusters.append({"name": f"Cluster-{len(clusters)+1}", "uri": p})

    # 2. Check MONGODB_URI and MONGODB_URI_*
    for env_key, env_val in os.environ.items():
        if (env_key == "MONGODB_URI" or env_key.startswith("MONGODB_URI_")) and env_key != "MONGODB_URIS":
            u = env_val.strip()
            if u and u not in seen_uris:
                seen_uris.add(u)
                label = env_key.replace("MONGODB_URI_", "").replace("MONGODB_URI", "Default Cluster")
                clusters.append({"name": label, "uri": u})

    return clusters


def ping_and_modify_cluster(
    cluster_info: Dict[str, str],
    db_name: str = "keepalive_db",
    collection_name: str = "keepalive_status",
    timeout_ms: int = 10000
) -> Dict[str, Any]:
    """
    Connect to a MongoDB cluster, ping it, and update dummy activity data in a collection.
    """
    name = cluster_info["name"]
    uri = cluster_info["uri"]
    masked = mask_uri(uri)

    result = {
        "name": name,
        "masked_uri": masked,
        "status": "FAILED",
        "duration_ms": 0,
        "message": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_pings": 0
    }

    start_time = time.time()

    if MongoClient is None:
        result["message"] = "pymongo library is not installed."
        return result

    client: Optional[MongoClient] = None
    try:
        logger.info(f"Connecting to MongoDB cluster [{name}] ({masked})...")
        
        # Configure TLS CA certificates if certifi is available
        client_kwargs = {
            "serverSelectionTimeoutMS": timeout_ms,
            "connectTimeoutMS": timeout_ms
        }
        try:
            import certifi
            client_kwargs["tlsCAFile"] = certifi.where()
        except ImportError:
            pass

        client = MongoClient(uri, **client_kwargs)
        
        # 1. Test connection with ping command
        logger.info(f"Pinging cluster [{name}]...")
        ping_res = client.admin.command("ping")
        if not ping_res or ping_res.get("ok") != 1:
            raise Exception(f"Admin ping response not OK: {ping_res}")

        # 2. Access database & collection with safe fallback
        db_target = db_name.strip() if (db_name and isinstance(db_name, str) and db_name.strip()) else ""
        coll_target = collection_name.strip() if (collection_name and isinstance(collection_name, str) and collection_name.strip()) else "keepalive_status"

        if not db_target:
            try:
                db = client.get_default_database()
                db_target = db.name if db.name else "keepalive_db"
            except Exception:
                db_target = "keepalive_db"
                db = client[db_target]
        else:
            db = client[db_target]

        collection = db[coll_target]

        # 3. Create / Modify test document with dummy data
        doc_id = "keepalive_ping_record"
        now_utc = datetime.now(timezone.utc)
        random_hash = secrets.token_hex(16)

        update_payload = {
            "$set": {
                "cluster_label": name,
                "status": "active",
                "last_ping_utc": now_utc.isoformat(),
                "dummy_payload": {
                    "hash": random_hash,
                    "note": "Automated cluster activity keep-alive ping.",
                    "environment": os.getenv("GITHUB_ACTIONS", "false") == "true" and "GitHub Actions" or "Local Environment"
                }
            },
            "$inc": {"total_pings": 1},
            "$currentDate": {"updated_at": True}
        }

        logger.info(f"Updating test document in collection [{db_target}.{coll_target}] on [{name}]...")
        up_res = collection.update_one({"_id": doc_id}, update_payload, upsert=True)

        # 4. Verify document write by reading it back
        saved_doc = collection.find_one({"_id": doc_id})
        if not saved_doc:
            raise Exception("Failed to retrieve updated keepalive document.")

        total_pings = saved_doc.get("total_pings", 1)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        result["status"] = "SUCCESS"
        result["duration_ms"] = duration_ms
        result["total_pings"] = total_pings
        result["message"] = f"Successfully updated collection '{coll_target}' in database '{db_target}' (Total pings: {total_pings})"
        logger.info(f"✅ [{name}] Keep-alive succeeded in {duration_ms}ms! Total pings: {total_pings}")

    except PyMongoError as pe:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        result["duration_ms"] = duration_ms
        result["message"] = f"MongoDB Error: {str(pe)}"
        logger.error(f"❌ [{name}] MongoDB error: {pe}")
    except Exception as e:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        result["duration_ms"] = duration_ms
        result["message"] = f"Error: {str(e)}"
        logger.error(f"❌ [{name}] Keep-alive failed: {e}")
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass

    return result


def send_discord_notification(webhook_url: str, results: List[Dict[str, Any]]) -> bool:
    """
    Send formatted summary report to Discord Webhook with rich embed.
    """
    if not webhook_url or not webhook_url.strip():
        logger.warning("No Discord Webhook URL provided. Skipping notification.")
        return False

    total_clusters = len(results)
    success_count = sum(1 for r in results if r["status"] == "SUCCESS")
    failed_count = total_clusters - success_count

    all_passed = (failed_count == 0 and total_clusters > 0)
    color = 0x2ECC71 if all_passed else 0xE74C3C  # Green vs Red

    status_title = "🚀 MongoDB Free Cluster Keep-Alive Summary"
    if not all_passed:
        status_title = "⚠️ MongoDB Free Cluster Keep-Alive Issue Detected"

    fields = []
    for r in results:
        icon = "✅" if r["status"] == "SUCCESS" else "❌"
        field_value = (
            f"**URI:** `{r['masked_uri']}`\n"
            f"**Latency:** `{r['duration_ms']} ms`\n"
            f"**Pings:** `{r['total_pings']}`\n"
            f"**Details:** {r['message']}"
        )
        fields.append({
            "name": f"{icon} {r['name']} — {r['status']}",
            "value": field_value,
            "inline": False
        })

    embed = {
        "title": status_title,
        "description": (
            f"Automated execution completed on **{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}**.\n"
            f"**Summary:** `{success_count}/{total_clusters}` clusters healthy."
        ),
        "color": color,
        "fields": fields,
        "footer": {
            "text": "MongoDB Cluster Automation • Keep-Alive Bot",
            "icon_url": "https://www.mongodb.com/assets/images/global/favicon.ico"
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    payload = {
        "username": "MongoDB Keep-Alive Bot",
        "avatar_url": "https://www.mongodb.com/assets/images/global/favicon.ico",
        "embeds": [embed]
    }

    try:
        logger.info("Sending notification report to Discord Webhook...")
        response = requests.post(webhook_url.strip(), json=payload, timeout=10)
        if response.status_code in (200, 204):
            logger.info("Successfully delivered Discord webhook notification.")
            return True
        else:
            logger.error(f"Failed to send Discord webhook. HTTP {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending Discord webhook: {e}")
        return False


def main() -> int:
    """
    Main entry point.
    """
    logger.info("==========================================")
    logger.info(" Starting MongoDB Cluster Keep-Alive Check ")
    logger.info("==========================================")

    raw_db = os.getenv("MONGODB_DB_NAME", "").strip()
    db_name = raw_db if raw_db else "keepalive_db"

    raw_coll = os.getenv("MONGODB_COLLECTION_NAME", "").strip()
    collection_name = raw_coll if raw_coll else "keepalive_status"

    discord_webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    clusters = parse_mongodb_uris()

    if not clusters:
        logger.error("❌ No MongoDB URIs found! Please set 'MONGODB_URIS' or 'MONGODB_URI' in environment variables.")
        if discord_webhook:
            send_discord_notification(discord_webhook, [{
                "name": "Configuration Error",
                "masked_uri": "N/A",
                "status": "FAILED",
                "duration_ms": 0,
                "total_pings": 0,
                "message": "No MongoDB connection URIs found in environment variables."
            }])
        return 1

    logger.info(f"Found {len(clusters)} MongoDB cluster URI(s) to process.")

    results: List[Dict[str, Any]] = []
    for cluster in clusters:
        res = ping_and_modify_cluster(cluster, db_name=db_name, collection_name=collection_name)
        results.append(res)

    # Print clean terminal summary
    logger.info("==========================================")
    logger.info("              EXECUTION SUMMARY           ")
    logger.info("==========================================")
    all_success = True
    for r in results:
        status_sym = "✅" if r["status"] == "SUCCESS" else "❌"
        logger.info(f"{status_sym} {r['name']} | {r['masked_uri']} | Status: {r['status']} ({r['duration_ms']}ms)")
        if r["status"] != "SUCCESS":
            all_success = False

    # Send Discord Webhook
    if discord_webhook:
        send_discord_notification(discord_webhook, results)
    else:
        logger.info("DISCORD_WEBHOOK_URL not configured. Skipping Discord notification.")

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())

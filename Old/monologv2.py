import os
import re
import math
import hmac
import hashlib
import uuid
import sqlite3
import logging
import datetime
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional, Tuple

import requests
import httpx
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request, HTTPException, Query, BackgroundTasks, status
from fastapi.responses import PlainTextResponse
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# =====================================================================
# CONFIGURATION & INITIALIZATION
# =====================================================================

DB_FILE = os.getenv("MONOLOG_DB_FILE", "monolog.db")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
APP_SECRET = os.getenv("META_APP_SECRET", "")
META_API_VERSION = "v21.0"
SAST_TIMEZONE = pytz.timezone("Africa/Johannesburg")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("monologv2")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)
scheduler = AsyncIOScheduler()

# =====================================================================
# 1. DATABASE SCHEMA & ACCESS LAYER
# =====================================================================

def get_db_connection() -> sqlite3.Connection:
    """Creates a database connection with dict row access, foreign keys, and write timeout."""
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Initializes tables and configures Write-Ahead Logging (WAL) for concurrency."""
    with get_db_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        cursor = conn.cursor()
        cursor.executescript("""
            -- Master Business Tenant Profile
            CREATE TABLE IF NOT EXISTS business_info (
                business_id TEXT PRIMARY KEY,
                business_name TEXT,
                primary_mail TEXT,
                primary_e_mail TEXT,
                website TEXT,
                core_business TEXT
            );

            CREATE TABLE IF NOT EXISTS business_whatsapp (
                business_id TEXT,
                w_number TEXT PRIMARY KEY,
                phone_number_id TEXT,
                FOREIGN KEY (business_id) REFERENCES business_info(business_id)
            );

            CREATE TABLE IF NOT EXISTS product_info_detail (
                product_id TEXT PRIMARY KEY,
                business_id TEXT,
                product_name TEXT,
                product_type TEXT,
                unit_measure TEXT,
                cost REAL,
                core_business TEXT,
                lead_times TEXT,
                FOREIGN KEY (business_id) REFERENCES business_info(business_id)
            );

            CREATE TABLE IF NOT EXISTS return_policy (
                product_id TEXT PRIMARY KEY,
                has_return_policy INTEGER,
                policy TEXT,
                FOREIGN KEY (product_id) REFERENCES product_info_detail(product_id)
            );

            CREATE TABLE IF NOT EXISTS operating_hours (
                business_id TEXT PRIMARY KEY,
                monday TEXT,
                tuesday TEXT,
                wednesday TEXT,
                thursday TEXT,
                friday TEXT,
                saturday TEXT,
                sunday TEXT,
                public_holiday TEXT,
                FOREIGN KEY (business_id) REFERENCES business_info(business_id)
            );

            CREATE TABLE IF NOT EXISTS business_location (
                business_id TEXT PRIMARY KEY,
                building TEXT,
                building_number TEXT,
                street TEXT,
                suburb TEXT,
                city TEXT,
                province TEXT,
                FOREIGN KEY (business_id) REFERENCES business_info(business_id)
            );

            CREATE TABLE IF NOT EXISTS human_escalation (
                business_id TEXT PRIMARY KEY,
                man_number TEXT,
                response_time TEXT,
                FOREIGN KEY (business_id) REFERENCES business_info(business_id)
            );

            CREATE TABLE IF NOT EXISTS service_area (
                business_id TEXT PRIMARY KEY,
                service_province TEXT,
                service_city TEXT,
                service_suburb TEXT,
                delivery_cost TEXT,
                FOREIGN KEY (business_id) REFERENCES business_info(business_id)
            );

            -- Customer CRM Directory with Geometry Tracking
            CREATE TABLE IF NOT EXISTS client_table (
                customer_id TEXT PRIMARY KEY,
                business_id TEXT,
                name TEXT,
                surname TEXT,
                mobile_number TEXT UNIQUE,
                email TEXT,
                address TEXT,
                latitude REAL,
                longitude REAL,
                first_contact_source TEXT DEFAULT 'WHATSAPP_INBOUND',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (business_id) REFERENCES business_info(business_id)
            );

            CREATE TABLE IF NOT EXISTS reminder_table (
                reminder_id TEXT PRIMARY KEY,
                business_id TEXT,
                detail TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (business_id) REFERENCES business_info(business_id)
            );

            -- Public Informational Events (Trade Shows, Expos, Pop-ups)
            CREATE TABLE IF NOT EXISTS business_events (
                event_id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL,
                event_name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                start_time TEXT,
                end_time TEXT,
                venue_address TEXT NOT NULL,
                ticket_fee REAL DEFAULT 0.0,
                description TEXT,
                owner_attending INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(business_id) REFERENCES business_info(business_id)
            );

            -- Customer Appointments (60-min slots, 40-min buffers, lifecycle status)
            CREATE TABLE IF NOT EXISTS customer_appointments (
                appointment_id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                service_id TEXT,
                subject TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                location TEXT,
                latitude REAL,
                longitude REAL,
                status TEXT DEFAULT 'PENDING_CONFIRMATION',
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(business_id) REFERENCES business_info(business_id),
                FOREIGN KEY(customer_id) REFERENCES client_table(customer_id)
            );

            CREATE TABLE IF NOT EXISTS open_queries (
                query_id TEXT PRIMARY KEY,
                customer_id TEXT,
                business_id TEXT,
                status TEXT DEFAULT 'OPEN',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES client_table(customer_id),
                FOREIGN KEY (business_id) REFERENCES business_info(business_id)
            );

            CREATE TABLE IF NOT EXISTS query_items (
                item_id TEXT PRIMARY KEY,
                query_id TEXT,
                product_id TEXT,
                qty INTEGER,
                unit_price REAL,
                FOREIGN KEY (query_id) REFERENCES open_queries(query_id),
                FOREIGN KEY (product_id) REFERENCES product_info_detail(product_id)
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id TEXT,
                sender_phone TEXT,
                role TEXT,
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (business_id) REFERENCES business_info(business_id)
            );

            CREATE INDEX IF NOT EXISTS idx_chat_history 
            ON chat_history (business_id, sender_phone, created_at);

            -- Isolated Conversation Audit Log (No System Messages)
            CREATE TABLE IF NOT EXISTS conversation_audit_log (
                log_id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL,
                sender_phone TEXT NOT NULL,
                direction TEXT NOT NULL,
                channel TEXT DEFAULT 'WHATSAPP',
                message_type TEXT NOT NULL,
                raw_payload_text TEXT,
                media_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- Dedicated System Diagnostic Log (Troubleshooting, Tool Errors, HTTP Codes)
            CREATE TABLE IF NOT EXISTS system_event_log (
                event_id TEXT PRIMARY KEY,
                business_id TEXT,
                severity TEXT NOT NULL,
                component TEXT NOT NULL,
                message TEXT NOT NULL,
                context_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()


def generate_custom_id(prefix: str) -> str:
    """Generates a collision-resistant UUID4 prefixed identifier."""
    return f"{prefix}_{uuid.uuid4().hex}"


def normalize_phone(phone: str) -> str:
    """Strips all non-digit characters for standardized comparison."""
    return "".join(filter(str.isdigit, str(phone)))


def log_conversation(
    business_id: str,
    sender_phone: str,
    direction: str,
    message_type: str,
    text: str,
    media_url: Optional[str] = None
) -> None:
    """Logs conversation events strictly without system clutter."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO conversation_audit_log 
                (log_id, business_id, sender_phone, direction, channel, message_type, raw_payload_text, media_url)
                VALUES (?, ?, ?, ?, 'WHATSAPP', ?, ?, ?)
                """,
                (generate_custom_id("cal"), business_id, normalize_phone(sender_phone), direction, message_type, text, media_url)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to write conversation audit log: {e}")


def log_system_event(
    severity: str,
    component: str,
    message: str,
    business_id: Optional[str] = None,
    context: Optional[str] = None
) -> None:
    """Logs system events, errors, tool calls, and diagnostics."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO system_event_log (event_id, business_id, severity, component, message, context_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (generate_custom_id("sel"), business_id, severity, component, message, context)
            )
            conn.commit()
    except Exception as e:
        logger.critical(f"Fatal: Unable to record system diagnostic log: {e}")


def save_chat_turn(business_id: str, sender_phone: str, role: str, content: str) -> None:
    """Stores a message turn in conversation memory."""
    clean_phone = normalize_phone(sender_phone)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_history (business_id, sender_phone, role, content)
            VALUES (?, ?, ?, ?)
            """,
            (business_id, clean_phone, role, content)
        )
        conn.commit()


def fetch_recent_chat_history(business_id: str, sender_phone: str, limit: int = 8) -> List[Dict[str, str]]:
    """Retrieves recent conversation turns in chronological order."""
    clean_phone = normalize_phone(sender_phone)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content FROM chat_history
            WHERE business_id = ? AND sender_phone = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (business_id, clean_phone, limit)
        )
        rows = cursor.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def resolve_business_id_from_destination(destination_number: str) -> Optional[str]:
    """Resolves business tenant using the incoming WhatsApp business line."""
    clean_number = normalize_phone(destination_number)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT business_id FROM business_whatsapp 
            WHERE w_number = ? OR w_number LIKE ?
            LIMIT 1
            """,
            (clean_number, f"%{clean_number}"),
        )
        row = cursor.fetchone()
        return row["business_id"] if row else None


def is_owner_phone(business_id: str, sender_phone: str) -> bool:
    """Validates if sender matches the authorized manager number via normalized comparison."""
    clean_sender = normalize_phone(sender_phone)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT man_number FROM human_escalation WHERE business_id = ?",
            (business_id,),
        )
        row = cursor.fetchone()
        if not row or not row["man_number"]:
            return False

        clean_man = normalize_phone(row["man_number"])
        if clean_sender == clean_man:
            return True
        if len(clean_sender) >= 9 and len(clean_man) >= 9:
            return clean_sender[-9:] == clean_man[-9:]
        return False


def ensure_client_persisted(
    business_id: str,
    sender_phone: str,
    profile_name: str = "",
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> str:
    """Saves all customer details on first contact regardless of whether they place an order."""
    clean_mobile = normalize_phone(sender_phone)
    name_parts = profile_name.strip().split(" ", 1) if profile_name else ["Customer", ""]
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT customer_id, name, latitude, longitude FROM client_table WHERE business_id = ? AND mobile_number = ?",
            (business_id, clean_mobile),
        )
        row = cursor.fetchone()
        if row:
            customer_id = row["customer_id"]
            cursor.execute(
                """
                UPDATE client_table
                SET name = CASE WHEN name = 'Customer' OR name IS NULL THEN ? ELSE name END,
                    latitude = COALESCE(?, latitude),
                    longitude = COALESCE(?, longitude)
                WHERE customer_id = ?
                """,
                (first_name, latitude, longitude, customer_id),
            )
        else:
            customer_id = generate_custom_id("cust")
            cursor.execute(
                """
                INSERT INTO client_table 
                (customer_id, business_id, name, surname, mobile_number, latitude, longitude, first_contact_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'WHATSAPP_INBOUND')
                """,
                (customer_id, business_id, first_name, last_name, clean_mobile, latitude, longitude),
            )
        conn.commit()
        return customer_id


def fetch_business_profile(business_id: str) -> Dict[str, Any]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM business_info WHERE business_id = ?", (business_id,))
        row = cursor.fetchone()
        return dict(row) if row else {}


def fetch_operating_hours(business_id: str) -> Dict[str, Any]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM operating_hours WHERE business_id = ?", (business_id,))
        row = cursor.fetchone()
        return dict(row) if row else {}


def fetch_location_and_service_area(business_id: str) -> Dict[str, Any]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM business_location WHERE business_id = ?", (business_id,))
        loc = cursor.fetchone()
        cursor.execute("SELECT * FROM service_area WHERE business_id = ?", (business_id,))
        service = cursor.fetchone()
        return {
            "location": dict(loc) if loc else None,
            "service_area": dict(service) if service else None,
        }


def search_catalog(business_id: str, query: str = "") -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        sql = """
            SELECT 
                p.product_id, p.product_name, p.product_type, p.unit_measure, 
                p.cost, p.core_business, p.lead_times, r.has_return_policy, r.policy
            FROM product_info_detail p
            LEFT JOIN return_policy r ON p.product_id = r.product_id
            WHERE p.business_id = ?
        """
        params: List[Any] = [business_id]
        if query:
            sql += " AND (p.product_name LIKE ? OR p.product_type LIKE ? OR p.core_business LIKE ?)"
            wildcard = f"%{query}%"
            params.extend([wildcard, wildcard, wildcard])

        cursor.execute(sql, tuple(params))
        return [dict(r) for r in cursor.fetchall()]


def fetch_escalation_details(business_id: str) -> Dict[str, Any]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM human_escalation WHERE business_id = ?", (business_id,))
        row = cursor.fetchone()
        return dict(row) if row else {}


def upsert_client(
    business_id: str,
    mobile_number: str,
    name: str,
    surname: str,
    email: str = "",
    address: str = "",
) -> str:
    clean_mobile = normalize_phone(mobile_number)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT customer_id FROM client_table WHERE business_id = ? AND mobile_number = ?",
            (business_id, clean_mobile),
        )
        row = cursor.fetchone()
        if row:
            customer_id = row["customer_id"]
            cursor.execute(
                """
                UPDATE client_table
                SET name = ?, surname = ?, 
                    email = COALESCE(NULLIF(?, ''), email), 
                    address = COALESCE(NULLIF(?, ''), address)
                WHERE customer_id = ?
                """,
                (name, surname, email, address, customer_id),
            )
        else:
            customer_id = generate_custom_id("cust")
            cursor.execute(
                """
                INSERT INTO client_table (customer_id, business_id, name, surname, mobile_number, email, address)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (customer_id, business_id, name, surname, clean_mobile, email, address),
            )
        conn.commit()
        return customer_id


def create_order_lead_query(business_id: str, customer_id: str, items: List[Dict[str, Any]]) -> str:
    query_id = generate_custom_id("qry")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO open_queries (query_id, customer_id, business_id, status) VALUES (?, ?, ?, 'OPEN')",
            (query_id, customer_id, business_id),
        )
        for it in items:
            cursor.execute(
                """
                INSERT INTO query_items (item_id, query_id, product_id, qty, unit_price)
                VALUES (?, ?, ?, ?, ?)
                """,
                (generate_custom_id("item"), query_id, it.get("product_id"), it.get("qty", 1), it.get("unit_price", 0.0)),
            )
        conn.commit()
        return query_id


# =====================================================================
# 2. WHATSAPP OUTBOUND & MEDIA RETRIEVAL
# =====================================================================

def send_whatsapp_message(recipient_phone: str, message_text: str, business_id: Optional[str] = None) -> None:
    """Dispatches outbound text messages via Meta Graph API and logs them."""
    clean_recipient = normalize_phone(recipient_phone)
    url = f"https://graph.facebook.com/{META_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "messaging_product": "whatsapp",
        "to": clean_recipient,
        "type": "text",
        "text": {"body": message_text},
    }
    try:
        response = requests.post(url, json=data, headers=headers, timeout=10)
        response.raise_for_status()
        logger.info(f"Outbound WhatsApp dispatched to +{clean_recipient}")
        if business_id:
            log_conversation(business_id, clean_recipient, "OUTBOUND", "TEXT", message_text)
    except Exception as e:
        err_msg = f"Failed outbound WhatsApp to +{clean_recipient}: {e}"
        logger.error(err_msg)
        log_system_event("ERROR", "META_OUTBOUND", err_msg, business_id=business_id)


async def download_meta_audio(media_id: str) -> bytes:
    """Fetches and downloads audio binary from Meta Graph API."""
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient() as client:
        meta_res = await client.get(f"https://graph.facebook.com/{META_API_VERSION}/{media_id}", headers=headers)
        meta_res.raise_for_status()
        media_url = meta_res.json().get("url")

        audio_res = await client.get(media_url, headers=headers)
        audio_res.raise_for_status()
        return audio_res.content


# =====================================================================
# 3. ADVANCED SCHEDULING ENGINE (40-MIN BUFFERS & CONFLICT CHECKS)
# =====================================================================

def is_within_operating_hours(business_id: str, date_str: str, start_time_str: str, end_time_str: str) -> Tuple[bool, str]:
    """Validates that requested slot falls within the tenant's configured operating hours."""
    hours = fetch_operating_hours(business_id)
    if not hours:
        return True, ""  # No restrictions configured

    try:
        booking_date = datetime.date.fromisoformat(date_str)
        day_name = booking_date.strftime("%A").lower()
        day_schedule = hours.get(day_name, "")

        if not day_schedule or "closed" in day_schedule.lower():
            return False, f"The business is closed on {day_name.capitalize()}s."

        parts = day_schedule.split("-")
        if len(parts) != 2:
            return True, ""

        op_start = datetime.datetime.strptime(parts[0].strip(), "%H:%M").time()
        op_end = datetime.datetime.strptime(parts[1].strip(), "%H:%M").time()
        req_start = datetime.datetime.strptime(start_time_str, "%H:%M").time()
        req_end = datetime.datetime.strptime(end_time_str, "%H:%M").time()

        if req_start < op_start or req_end > op_end:
            return False, f"Requested time is outside operating hours ({day_schedule.strip()})."

        return True, ""
    except Exception as e:
        log_system_event("WARN", "HOURS_CHECK", f"Could not parse hours: {e}", business_id=business_id)
        return True, ""


def check_appointment_conflict_with_buffer(
    business_id: str,
    date_str: str,
    start_time_str: str,
    buffer_minutes: int = 40
) -> Tuple[bool, str]:
    """
    Enforces a strict 40-minute buffer window around existing commitments.
    Each slot defaults to 60 minutes duration.
    """
    fmt = "%H:%M"
    try:
        req_start_dt = datetime.datetime.strptime(start_time_str, fmt)
        req_end_dt = req_start_dt + datetime.timedelta(minutes=60)
        req_end_str = req_end_dt.strftime(fmt)

        valid_hours, reason = is_within_operating_hours(business_id, date_str, start_time_str, req_end_str)
        if not valid_hours:
            return False, reason

        req_envelope_start = (req_start_dt - datetime.timedelta(minutes=buffer_minutes)).time()
        req_envelope_end = (req_end_dt + datetime.timedelta(minutes=buffer_minutes)).time()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT appointment_id, subject, start_time, end_time 
                FROM customer_appointments
                WHERE business_id = ? 
                  AND appointment_date = ? 
                  AND status IN ('CONFIRMED', 'PENDING_CONFIRMATION')
                """,
                (business_id, date_str)
            )
            for row in cursor.fetchall():
                b_start = datetime.datetime.strptime(row["start_time"], fmt).time()
                b_end = datetime.datetime.strptime(row["end_time"], fmt).time()

                if not (req_envelope_end <= b_start or req_envelope_start >= b_end):
                    return False, f"Time conflict! An existing appointment '{row['subject']}' is booked ({row['start_time']}-{row['end_time']}). A {buffer_minutes}-min travel buffer is required."

        return True, req_end_str
    except ValueError as e:
        return False, f"Invalid time/date formatting: {e}"


# =====================================================================
# 4. SITE CLIENT HISTORY & HAVERSINE SPATIAL LOOKUP
# =====================================================================

def query_site_history_by_location(
    business_id: str,
    address_query: str = "",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: float = 0.15
) -> str:
    """Finds client history by GPS distance (150m radius) or fuzzy address matching."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        target_customer = None

        if lat is not None and lon is not None:
            cursor.execute(
                """
                SELECT customer_id, name, surname, address, latitude, longitude 
                FROM client_table 
                WHERE business_id = ? AND latitude IS NOT NULL AND longitude IS NOT NULL
                """,
                (business_id,)
            )
            min_dist = float("inf")
            for c in cursor.fetchall():
                c_lat, c_lon = c["latitude"], c["longitude"]
                dlat = math.radians(c_lat - lat)
                dlon = math.radians(c_lon - lon)
                a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(c_lat)) * math.sin(dlon / 2)**2
                dist = 6371.0 * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
                if dist < min_dist and dist <= radius_km:
                    min_dist = dist
                    target_customer = c

        if not target_customer and address_query:
            cursor.execute(
                """
                SELECT customer_id, name, surname, address, mobile_number 
                FROM client_table 
                WHERE business_id = ? AND address LIKE ?
                LIMIT 1
                """,
                (business_id, f"%{address_query}%")
            )
            target_customer = cursor.fetchone()

        if not target_customer:
            return "No client records located matching that site or coordinate radius."

        cid = target_customer["customer_id"]
        cursor.execute(
            """
            SELECT appointment_date, start_time, subject, status, notes 
            FROM customer_appointments 
            WHERE customer_id = ? AND status = 'COMPLETED'
            ORDER BY appointment_date DESC
            """,
            (cid,)
        )
        completed_jobs = cursor.fetchall()

        c_name = f"{target_customer['name'] or ''} {target_customer['surname'] or ''}".strip()
        history_lines = [f"Site Work History for: {c_name} (Addr: {target_customer['address'] or 'N/A'})"]

        if not completed_jobs:
            history_lines.append("No previously completed jobs on record for this customer site.")
        else:
            for job in completed_jobs:
                history_lines.append(
                    f"• [{job['appointment_date']}]: {job['subject']}\n"
                    f"  Technician Notes: {job['notes'] or 'No work notes filed'}"
                )

        return "\n".join(history_lines)


# =====================================================================
# 5. AGENT EXECUTION RUNNERS (CUSTOMER & OWNER MODES)
# =====================================================================

def run_customer_agent(
    business_id: str,
    customer_phone: str,
    user_query: Optional[str] = None,
    audio_bytes: Optional[bytes] = None
) -> str:
    business_data = fetch_business_profile(business_id)
    business_name = business_data.get("business_name", "the business")

    def get_business_overview() -> str:
        """Retrieves company description, contact email, and core business overview."""
        info = fetch_business_profile(business_id)
        return (
            f"Business: {info.get('business_name')}\n"
            f"Overview: {info.get('core_business')}\n"
            f"Website: {info.get('website')}\n"
            f"Email: {info.get('primary_e_mail')}\n"
            f"Phone: {info.get('primary_mail')}"
        )

    def get_trading_hours() -> str:
        """Retrieves operating hours for weekdays, weekends, and public holidays."""
        hours = fetch_operating_hours(business_id)
        if not hours:
            return "Operating hours not found in database."
        return "\n".join([f"{k.capitalize()}: {v}" for k, v in hours.items() if k != "business_id"])

    def get_physical_location_and_service_area() -> str:
        """Retrieves branch address, service suburbs, and call-out delivery costs."""
        data = fetch_location_and_service_area(business_id)
        loc = data.get("location") or {}
        srv = data.get("service_area") or {}
        addr = f"{loc.get('building_number', '')} {loc.get('street', '')}, {loc.get('suburb', '')}, {loc.get('city', '')}".strip()
        return f"Address: {addr}\nCoverage: {srv.get('service_suburb')}, {srv.get('service_city')}\nCall-out: {srv.get('delivery_cost')}"

    def get_products_or_services(search_term: str = "") -> str:
        """Looks up catalog items, prices, lead times, and warranty policies."""
        items = search_catalog(business_id, query=search_term)
        if not items:
            return "No matching products or services found."
        output = []
        for it in items:
            output.append(
                f"- ID: {it['product_id']} | {it['product_name']} ({it['product_type']})\n"
                f"  Price: R{it['cost']} {it['unit_measure']} | Lead Time: {it['lead_times']}\n"
                f"  Warranty/Return: {it['policy'] or 'Standard terms apply'}"
            )
        return "\n\n".join(output)

    def get_public_events() -> str:
        """Retrieves upcoming trade shows, expos, and public promotional events."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT event_name, start_date, start_time, venue_address, ticket_fee, description, owner_attending
                FROM business_events
                WHERE business_id = ? AND start_date >= DATE('now')
                ORDER BY start_date ASC
                """,
                (business_id,)
            )
            rows = cursor.fetchall()
            if not rows:
                return "There are no public events or expos currently scheduled."
            events = []
            for r in rows:
                attending = "Yes - Owner will be present" if r["owner_attending"] else "Company exhibit only"
                fee = f"R{r['ticket_fee']}" if r["ticket_fee"] > 0 else "Free Entry"
                events.append(
                    f"🎉 {r['event_name']}\n"
                    f"Date: {r['start_date']} at {r['start_time'] or 'All day'}\n"
                    f"Location: {r['venue_address']}\n"
                    f"Admission: {fee} | Management Attending: {attending}\n"
                    f"Details: {r['description']}"
                )
            return "\n\n".join(events)

    def book_customer_appointment(date: str, start_time: str, service_description: str, address: str = "") -> str:
        """Books a 60-min service appointment on the owner's schedule with a 40-min buffer check."""
        is_free, end_time_or_reason = check_appointment_conflict_with_buffer(business_id, date, start_time, 40)
        if not is_free:
            return f"BOOKING_UNAVAILABLE: {end_time_or_reason}"

        cid = ensure_client_persisted(business_id, customer_phone)
        apt_id = generate_custom_id("apt")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO customer_appointments 
                (appointment_id, business_id, customer_id, subject, appointment_date, start_time, end_time, location, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_CONFIRMATION')
                """,
                (apt_id, business_id, cid, service_description, date, start_time, end_time_or_reason, address),
            )
            conn.commit()

        # Instant alert to business owner
        esc = fetch_escalation_details(business_id)
        if esc.get("man_number"):
            send_whatsapp_message(
                recipient_phone=esc["man_number"],
                message_text=(
                    f"📅 *New Appointment Booking Request*\n"
                    f"Ref: {apt_id}\n"
                    f"Customer: +{customer_phone}\n"
                    f"Date: {date} ({start_time} - {end_time_or_reason})\n"
                    f"Service: {service_description}\n"
                    f"Location: {address or 'Not specified'}\n"
                    f"Status: PENDING_CONFIRMATION"
                ),
                business_id=business_id
            )

        return f"SUCCESS: Appointment reserved for {date} at {start_time} (Ref: {apt_id}). Awaiting owner confirmation."

    def get_customer_appointment_status() -> str:
        """Allows customers to look up the status of appointments they booked."""
        cid = ensure_client_persisted(business_id, customer_phone)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT appointment_id, appointment_date, start_time, subject, status 
                FROM customer_appointments
                WHERE business_id = ? AND customer_id = ?
                ORDER BY created_at DESC LIMIT 5
                """,
                (business_id, cid)
            )
            rows = cursor.fetchall()
            if not rows:
                return "You have no active or historical appointments registered under this number."
            res = ["Your Registered Appointments:"]
            for r in rows:
                res.append(f"• Ref {r['appointment_id']} ({r['appointment_date']} @ {r['start_time']}): {r['subject']} -> Status: *{r['status']}*")
            return "\n".join(res)

    def submit_lead_and_order_request(name: str, surname: str, email: str, address: str, product_id: str, quantity: int = 1) -> str:
        """Registers lead details and records an open order query."""
        catalog = search_catalog(business_id)
        product = next((p for p in catalog if p["product_id"] == product_id), None)
        unit_price = float(product["cost"]) if product and product.get("cost") else 0.0

        cid = upsert_client(business_id, customer_phone, name, surname, email, address)
        qid = create_order_lead_query(business_id, cid, [{"product_id": product_id, "qty": quantity, "unit_price": unit_price}])

        esc = fetch_escalation_details(business_id)
        if esc.get("man_number"):
            send_whatsapp_message(
                recipient_phone=esc["man_number"],
                message_text=(
                    f"🌟 *New Order Inquiry ({qid})*\n"
                    f"Customer: {name} {surname} (+{customer_phone})\n"
                    f"Item: {product['product_name'] if product else product_id} x{quantity}\n"
                    f"Address: {address}"
                ),
                business_id=business_id
            )
        return f"SUCCESS: Order inquiry registered with Reference ID: {qid}."

    def escalate_unanswered_query_to_owner(reason: str) -> str:
        """Escalates missing information or complex queries to the business owner."""
        esc = fetch_escalation_details(business_id)
        man_number = esc.get("man_number")
        resp_time = esc.get("response_time", "within 24 hours")
        if man_number:
            send_whatsapp_message(
                recipient_phone=man_number,
                message_text=f"🚨 *Escalation from +{customer_phone}*\nReason: {reason}\nTarget Turnaround: {resp_time}",
                business_id=business_id
            )
        return f"Query escalated to management. Expected turnaround: {resp_time}."

    system_instruction = (
        f"You are the official WhatsApp assistant for {business_name}.\n"
        "STRICT COMPLIANCE RULES:\n"
        "1. ONLY state facts returned by your tools. Never guess prices, slots, or hours.\n"
        "2. If requested details are absent, invoke `escalate_unanswered_query_to_owner`.\n"
        "3. Customers can book appointments using `book_customer_appointment` or check status via `get_customer_appointment_status`.\n"
        "4. Inquire about public events, expos, and trade shows using `get_public_events`.\n"
        "5. ALWAYS reply in polite, concise WhatsApp-formatted text."
    )

    contents_payload: List[types.Content] = []
    for turn in fetch_recent_chat_history(business_id, customer_phone, limit=8):
        contents_payload.append(
            types.Content(
                role="user" if turn["role"] == "user" else "model",
                parts=[types.Part.from_text(text=turn["content"])]
            )
        )

    current_parts: List[types.Part] = []
    if audio_bytes:
        current_parts.append(types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"))
    if user_query:
        current_parts.append(types.Part.from_text(text=user_query))

    contents_payload.append(types.Content(role="user", parts=current_parts))

    try:
        response = gemini_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=contents_payload,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[
                    get_business_overview,
                    get_trading_hours,
                    get_physical_location_and_service_area,
                    get_products_or_services,
                    get_public_events,
                    book_customer_appointment,
                    get_customer_appointment_status,
                    submit_lead_and_order_request,
                    escalate_unanswered_query_to_owner,
                ],
                temperature=0.0,
            ),
        )
        reply_text = response.text.strip()
    except Exception as e:
        log_system_event("ERROR", "GEMINI_CUSTOMER_AGENT", str(e), business_id=business_id)
        reply_text = "I experienced a technical issue retrieving details. Your message has been forwarded to management."

    input_summary = user_query or "[Voice Note Audio]"
    save_chat_turn(business_id, customer_phone, "user", input_summary)
    save_chat_turn(business_id, customer_phone, "model", reply_text)
    return reply_text


def run_owner_agent(
    business_id: str,
    owner_phone: str,
    user_query: Optional[str] = None,
    audio_bytes: Optional[bytes] = None,
    location_pin: Optional[Dict[str, float]] = None
) -> str:
    business_data = fetch_business_profile(business_id)
    business_name = business_data.get("business_name", "your business")

    def add_reminder(detail: str) -> str:
        """Logs a new to-do task for the owner."""
        rid = generate_custom_id("rem")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO reminder_table (reminder_id, business_id, detail) VALUES (?, ?, ?)", (rid, business_id, detail))
            conn.commit()
        return f"Reminder stored: '{detail}'"

    def list_reminders() -> str:
        """Lists active to-dos."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT detail, created_at FROM reminder_table WHERE business_id = ? ORDER BY created_at DESC", (business_id,))
            rows = cursor.fetchall()
            return "\n".join([f"• {r['detail']}" for r in rows]) if rows else "No active reminders."

    def list_schedule_appointments(date: str = "") -> str:
        """Lists appointments for a given date (default today)."""
        target = date if date else datetime.date.today().isoformat()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT appointment_id, start_time, end_time, subject, location, status 
                FROM customer_appointments 
                WHERE business_id = ? AND appointment_date = ?
                ORDER BY start_time ASC
                """,
                (business_id, target)
            )
            rows = cursor.fetchall()
            if not rows:
                return f"No appointments scheduled for {target}."
            # Include ID so Gemini can reference it for updates/cancellations
            return f"Appointments for {target}:\n" + "\n".join([
                f"• ID: {r['appointment_id']} | [{r['start_time']}-{r['end_time']}] {r['subject']} ({r['location']}) [{r['status']}]"
                for r in rows
            ])

    def update_appointment_status(
        appointment_id: str = "",
        time: str = "",
        date: str = "",
        new_status: str = "CANCELLED",
        work_notes: str = ""
    ) -> str:
        """
        Updates an appointment status ('CONFIRMED', 'CANCELLED', 'COMPLETED').
        Can identify the appointment by either appointment_id OR by time (HH:MM) and date (YYYY-MM-DD).
        """
        target_date = date if date else datetime.date.today().isoformat()
        clean_status = new_status.upper()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            if appointment_id:
                cursor.execute(
                    """
                    UPDATE customer_appointments 
                    SET status = ?, notes = COALESCE(NULLIF(?, ''), notes)
                    WHERE appointment_id = ? AND business_id = ?
                    """,
                    (clean_status, work_notes, appointment_id, business_id)
                )
            elif time:
                cursor.execute(
                    """
                    UPDATE customer_appointments 
                    SET status = ?, notes = COALESCE(NULLIF(?, ''), notes)
                    WHERE start_time = ? AND appointment_date = ? AND business_id = ?
                    """,
                    (clean_status, work_notes, time, target_date, business_id)
                )
            else:
                return "Error: You must provide either the appointment_id or the start time."

            if cursor.rowcount == 0:
                ref = appointment_id if appointment_id else f"{target_date} at {time}"
                return f"No appointment found matching {ref} to update."
            
            conn.commit()
            ref = appointment_id if appointment_id else f"at {time} on {target_date}"
            return f"Success: Appointment {ref} has been marked as {clean_status}."

    def create_business_event(
        event_name: str,
        start_date: str,
        venue_address: str,
        start_time: str = "",
        ticket_fee: float = 0.0,
        description: str = "",
        owner_attending: bool = True
    ) -> str:
        """Publishes a public event or trade show for customer inquiries (purely informational)."""
        eid = generate_custom_id("evt")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO business_events 
                (event_id, business_id, event_name, start_date, start_time, venue_address, ticket_fee, description, owner_attending)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (eid, business_id, event_name, start_date, start_time, venue_address, ticket_fee, description, 1 if owner_attending else 0)
            )
            conn.commit()
        return f"Public event '{event_name}' published for {start_date} at {venue_address}."

    def get_site_client_history(address: str = "") -> str:
        """Fetches historical work done for a client via site address or current GPS location."""
        lat = location_pin.get("lat") if location_pin else None
        lon = location_pin.get("lon") if location_pin else None
        return query_site_history_by_location(business_id=business_id, address_query=address, lat=lat, lon=lon)

    system_instruction = (
        f"You are the executive assistant to the owner of {business_name}.\n"
        "CAPABILITIES:\n"
        "- Manage to-dos (`add_reminder`, `list_reminders`).\n"
        "- Inspect appointments (`list_schedule_appointments`).\n"
        "- Update appointment status and log work done (`update_appointment_status`).\n"
        "- Create public events/expos (`create_business_event`).\n"
        "- Look up historical on-site work via GPS or address (`get_site_client_history`).\n"
        "Tone: Crisp, organized, and focused on business execution."
    )

    contents_payload: List[types.Content] = []
    for turn in fetch_recent_chat_history(business_id, owner_phone, limit=8):
        contents_payload.append(
            types.Content(
                role="user" if turn["role"] == "user" else "model",
                parts=[types.Part.from_text(text=turn["content"])]
            )
        )

    current_parts: List[types.Part] = []
    if audio_bytes:
        current_parts.append(types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"))
    if user_query:
        current_parts.append(types.Part.from_text(text=user_query))
    if location_pin:
        current_parts.append(types.Part.from_text(text=f"[Location Coordinates: {location_pin['lat']}, {location_pin['lon']}]"))

    contents_payload.append(types.Content(role="user", parts=current_parts))

    try:
        response = gemini_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=contents_payload,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[
                    add_reminder,
                    list_reminders,
                    list_schedule_appointments,
                    update_appointment_status,
                    create_business_event,
                    get_site_client_history,
                ],
                temperature=0.0,
            ),
        )
        reply_text = response.text.strip()
    except Exception as e:
        log_system_event("ERROR", "GEMINI_OWNER_AGENT", str(e), business_id=business_id)
        reply_text = "An error occurred executing your request. Please check system logs."

    input_summary = user_query or "[Voice Note/Location Input]"
    save_chat_turn(business_id, owner_phone, "user", input_summary)
    save_chat_turn(business_id, owner_phone, "model", reply_text)
    return reply_text


# =====================================================================
# 6. INBOUND DISPATCH & EXPLICIT RELAY INTERCEPTION
# =====================================================================

async def handle_owner_relay_message(business_id: str, text: str) -> Optional[str]:
    """Intercepts the explicit pattern 'Tell Client [Name]: [Message]' and dispatches outbound."""
    match = re.match(r"^tell\s+client\s+([a-zA-Z\s]+?)\s*:\s*(.+)$", text, re.IGNORECASE)
    if not match:
        return None

    target_name, message_body = match.group(1).strip(), match.group(2).strip()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT mobile_number, name, surname FROM client_table
            WHERE business_id = ? AND (LOWER(name) LIKE ? OR LOWER(surname) LIKE ?)
            LIMIT 1
            """,
            (business_id, f"%{target_name.lower()}%", f"%{target_name.lower()}%")
        )
        client = cursor.fetchone()

    if not client or not client["mobile_number"]:
        return f"Could not find a registered customer matching '{target_name}'."

    client_phone = client["mobile_number"]
    full_name = f"{client['name'] or ''} {client['surname'] or ''}".strip()

    send_whatsapp_message(recipient_phone=client_phone, message_text=message_body, business_id=business_id)
    return f"Relayed message to {full_name} (+{client_phone}): \"{message_body}\""


async def process_incoming_payload(
    destination_phone: str,
    sender_phone: str,
    profile_name: str,
    message_type: str,
    text_content: Optional[str] = None,
    media_id: Optional[str] = None,
    location_data: Optional[Dict[str, float]] = None
) -> None:
    business_id = resolve_business_id_from_destination(destination_phone)
    if not business_id:
        log_system_event("WARN", "DISPATCHER", f"No tenant found for receiving line +{destination_phone}")
        return

    # Extract coordinates if present
    lat = location_data.get("lat") if location_data else None
    lon = location_data.get("lon") if location_data else None

    # Passive persistence: register customer profile immediately
    ensure_client_persisted(business_id, sender_phone, profile_name=profile_name, latitude=lat, longitude=lon)

    # Inbound logging to conversation audit trail
    log_summary = text_content or f"[{message_type.upper()} PAYLOAD]"
    log_conversation(business_id, sender_phone, "INBOUND", message_type.upper(), log_summary, media_id)

    # Audio retrieval if voice note
    audio_bytes: Optional[bytes] = None
    if message_type in ["audio", "voice"] and media_id:
        try:
            audio_bytes = await download_meta_audio(media_id)
        except Exception as e:
            log_system_event("ERROR", "AUDIO_DOWNLOAD", f"Failed downloading media {media_id}: {e}", business_id=business_id)
            send_whatsapp_message(sender_phone, "Sorry, I could not process your voice note. Please try again.", business_id)
            return

    # Routing: Owner Mode vs Customer Mode
    if is_owner_phone(business_id, sender_phone):
        logger.info(f"[OWNER MODE] Authenticated owner +{sender_phone} on tenant {business_id}")

        # Intercept explicit relay command: "Tell Client [Name]: [Message]"
        if text_content:
            relay_result = await handle_owner_relay_message(business_id, text_content)
            if relay_result:
                send_whatsapp_message(sender_phone, relay_result, business_id)
                return

        reply_text = run_owner_agent(
            business_id=business_id,
            owner_phone=sender_phone,
            user_query=text_content,
            audio_bytes=audio_bytes,
            location_pin=location_data
        )
    else:
        logger.info(f"[CUSTOMER MODE] Customer +{sender_phone} on tenant {business_id}")
        reply_text = run_customer_agent(
            business_id=business_id,
            customer_phone=sender_phone,
            user_query=text_content,
            audio_bytes=audio_bytes
        )

    send_whatsapp_message(recipient_phone=sender_phone, message_text=reply_text, business_id=business_id)


# =====================================================================
# 7. AUTOMATED 09:00 SAST MORNING DIGEST CRON JOB
# =====================================================================

async def dispatch_daily_morning_digest() -> None:
    """Dispatches daily 09:00 AM SAST agenda summaries to business owners."""
    today_str = datetime.datetime.now(SAST_TIMEZONE).strftime("%Y-%m-%d")
    logger.info(f"Triggering 09:00 SAST morning briefing for {today_str}")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT business_id, man_number FROM human_escalation WHERE man_number IS NOT NULL")
        tenants = cursor.fetchall()

        for business_id, owner_phone in tenants:
            cursor.execute(
                """
                SELECT start_time, end_time, subject, location 
                FROM customer_appointments 
                WHERE business_id = ? AND appointment_date = ? AND status != 'CANCELLED'
                ORDER BY start_time ASC
                """,
                (business_id, today_str)
            )
            appts = cursor.fetchall()

            cursor.execute("SELECT detail FROM reminder_table WHERE business_id = ?", (business_id,))
            reminders = cursor.fetchall()

            briefing = [f"🌅 *Good Morning! Here is your Monolog Agenda for {today_str}:*\n"]
            briefing.append("📅 *Today's Appointments:*")
            if appts:
                for a in appts:
                    briefing.append(f"• {a['start_time']} - {a['end_time']}: {a['subject']} @ {a['location'] or 'On site'}")
            else:
                briefing.append("• No appointments booked for today.")

            briefing.append("\n📝 *Active To-Dos:*")
            if reminders:
                for r in reminders:
                    briefing.append(f"• {r['detail']}")
            else:
                briefing.append("• No pending tasks.")

            msg = "\n".join(briefing)
            send_whatsapp_message(recipient_phone=owner_phone, message_text=msg, business_id=business_id)


# =====================================================================
# 8. LIFESPAN, FASTAPI ROUTES & WEBHOOK SECURITY
# =====================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Project Monolog database initialized with WAL mode and dual audit logs.")
    # Register 09:00 AM South African Standard Time Cron
    scheduler.add_job(
        dispatch_daily_morning_digest,
        trigger=CronTrigger(hour=9, minute=0, timezone=SAST_TIMEZONE),
        id="morning_digest_sast",
        replace_existing=True
    )
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="Project Monolog WhatsApp Agent Engine", lifespan=lifespan)


def verify_meta_signature(raw_payload: bytes, signature_header: Optional[str]) -> bool:
    """Validates incoming payload against Meta's HMAC-SHA256 signature."""
    if not signature_header or not APP_SECRET:
        return False
    if not signature_header.startswith("sha256="):
        return False

    expected_hash = signature_header.replace("sha256=", "").strip()
    computed_hmac = hmac.new(
        key=APP_SECRET.encode("utf-8"),
        msg=raw_payload,
        digestmod=hashlib.sha256,
    )
    return hmac.compare_digest(computed_hmac.hexdigest(), expected_hash)


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """Handles the Meta App Webhook verification handshake."""
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("Meta webhook challenge handshake successful.")
        return PlainTextResponse(content=hub_challenge, status_code=status.HTTP_200_OK)

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification token mismatch")


@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming WhatsApp events, verifies HMAC signatures, extracts
    payloads (Text, Voice/Audio, Location), and delegates to background execution.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if APP_SECRET and not verify_meta_signature(raw_body, signature):
        log_system_event("CRITICAL", "SECURITY", "Rejected unauthorized POST request: Invalid HMAC signature")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature digest")

    try:
        body = await request.json()
    except Exception as e:
        log_system_event("ERROR", "PAYLOAD_PARSER", f"Malformed JSON: {e}")
        return {"status": "bad_request"}, status.HTTP_400_BAD_REQUEST

    entry_list = body.get("entry", [])
    if not entry_list:
        return {"status": "ok"}

    changes = entry_list[0].get("changes", [])
    if not changes:
        return {"status": "ok"}

    value = changes[0].get("value", {})
    metadata = value.get("metadata", {})
    destination_phone = metadata.get("display_phone_number")
    contacts = value.get("contacts", [])
    profile_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""

    messages = value.get("messages", [])
    if messages and destination_phone:
        msg = messages[0]
        sender_phone = msg.get("from")
        msg_type = msg.get("type")

        user_text: Optional[str] = None
        media_id: Optional[str] = None
        location_data: Optional[Dict[str, float]] = None

        if msg_type == "text":
            user_text = msg.get("text", {}).get("body", "").strip()
        elif msg_type in ["audio", "voice"]:
            media_id = msg.get(msg_type, {}).get("id")
        elif msg_type == "location":
            loc = msg.get("location", {})
            location_data = {"lat": loc.get("latitude"), "lon": loc.get("longitude")}
            user_text = f"Pin drop: {location_data['lat']}, {location_data['lon']}"

        background_tasks.add_task(
            process_incoming_payload,
            destination_phone=destination_phone,
            sender_phone=sender_phone,
            profile_name=profile_name,
            message_type=msg_type,
            text_content=user_text,
            media_id=media_id,
            location_data=location_data
        )

    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("monologv2:app", host="0.0.0.0", port=8005, reload=True)
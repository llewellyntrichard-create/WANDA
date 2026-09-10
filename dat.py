import os
import sqlite3
import datetime

DB_FILE = os.getenv("MONOLOG_DB_FILE", "monolog.db")


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def seed_database():
    business_id = "biz_monolog_01"
    business_whatsapp = "27788109754"
    owner_phone = "27633579297"

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Business Info
        cursor.execute(
            """
            INSERT OR REPLACE INTO business_info (
                business_id, business_name, primary_mail, primary_e_mail, website, core_business
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                business_id,
                "Apex Plumbing & Electrical Solutions",
                "011 555 0199",
                "service@apexsolutions.co.za",
                "https://www.apexsolutions.co.za",
                "Residential and commercial electrical repairs, plumbing maintenance, and solar installations.",
            ),
        )

        # 2. Business WhatsApp Line (Routing Key)
        cursor.execute(
            """
            INSERT OR REPLACE INTO business_whatsapp (business_id, w_number)
            VALUES (?, ?)
            """,
            (business_id, business_whatsapp),
        )

        # 3. Human Escalation (Owner Mode Key & Alert Destination)
        cursor.execute(
            """
            INSERT OR REPLACE INTO human_escalation (business_id, man_number, response_time)
            VALUES (?, ?, ?)
            """,
            (business_id, owner_phone, "within 2 hours"),
        )

        # 4. Operating Hours
        cursor.execute(
            """
            INSERT OR REPLACE INTO operating_hours (
                business_id, monday, tuesday, wednesday, thursday, friday, saturday, sunday, public_holiday
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                business_id,
                "08:00 - 17:00",
                "08:00 - 17:00",
                "08:00 - 17:00",
                "08:00 - 17:00",
                "08:00 - 16:30",
                "09:00 - 13:00",
                "Closed (Emergency standby only)",
                "Closed",
            ),
        )

        # 5. Physical Location
        cursor.execute(
            """
            INSERT OR REPLACE INTO business_location (
                business_id, building, building_number, street, suburb, city, province
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                business_id,
                "Sandton View Commercial Park",
                "Unit 4B",
                "Main Road",
                "Bryanston",
                "Johannesburg",
                "Gauteng",
            ),
        )

        # 6. Service Area & Delivery / Call-out Cost
        cursor.execute(
            """
            INSERT OR REPLACE INTO service_area (
                business_id, service_province, service_city, service_suburb, delivery_cost
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                business_id,
                "Gauteng",
                "Johannesburg and Midrand",
                "Bryanston, Sandton, Fourways, Rivonia, Randburg, Rosebank",
                "R250 call-out inspection fee (waived if quote accepted)",
            ),
        )

        # 7. Products and Services Catalog
        products = [
            (
                "prod_drain_clear",
                business_id,
                "Emergency Drain Unblocking",
                "Plumbing Service",
                "per incident",
                850.0,
                "High-pressure water jetting and clearing of blocked internal or external pipes.",
                "Same day (within 2 to 4 hours)",
                1,
                "Workmanship guaranteed for 14 days after unblocking.",
            ),
            (
                "prod_geyser_elem",
                business_id,
                "Geyser Heating Element Replacement",
                "Maintenance",
                "per unit",
                1450.0,
                "Complete replacement of faulty thermostat and copper heating element, parts and labour included.",
                "1 business day",
                1,
                "12-month manufacturer replacement warranty on installed parts.",
            ),
            (
                "prod_db_audit",
                business_id,
                "Electrical DB Board Inspection & CoC",
                "Compliance & Electrical",
                "per property",
                1800.0,
                "Thorough safety test, earth-leakage audit, and Certificate of Compliance issuance.",
                "2 business days",
                0,
                "Assessment fees are non-refundable once on-site testing begins.",
            ),
            (
                "prod_solar_diag",
                business_id,
                "Solar Inverter Diagnostic & Battery Health Check",
                "Solar Service",
                "per system",
                950.0,
                "Diagnostic scan of inverter errors, firmware updates, and lithium battery health check.",
                "1 to 2 business days",
                1,
                "Follow-up visit included if diagnostic issue recurs within 7 days.",
            ),
        ]

        for p_id, b_id, name, p_type, uom, cost, core, lead, has_ret, pol in products:
            cursor.execute(
                """
                INSERT OR REPLACE INTO product_info_detail (
                    product_id, business_id, product_name, product_type, unit_measure, cost, core_business, lead_times
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (p_id, b_id, name, p_type, uom, cost, core, lead),
            )
            cursor.execute(
                """
                INSERT OR REPLACE INTO return_policy (product_id, has_return_policy, policy)
                VALUES (?, ?, ?)
                """,
                (p_id, has_ret, pol),
            )

        # 8. Sample Owner Reminders (for testing Owner Mode)
        cursor.execute("DELETE FROM reminder_table WHERE business_id = ?", (business_id,))
        cursor.execute(
            """
            INSERT INTO reminder_table (reminder_id, business_id, detail)
            VALUES 
                ('rem_test_01', ?, 'Order 2x 3kW Kwikot heating elements from supplier'),
                ('rem_test_02', ?, 'Send monthly commercial invoice to Sandton View Body Corporate')
            """,
            (business_id, business_id),
        )

        # 9. Sample Scheduled Appointments (for testing Conflict Detection and Schedule Listing)
        today = datetime.date.today().isoformat()
        cursor.execute("DELETE FROM scheduler WHERE business_id = ?", (business_id,))
        cursor.execute(
            """
            INSERT INTO scheduler (sched_id, business_id, subject, date, time, location)
            VALUES 
                ('sch_test_01', ?, 'On-site DB Board Inspection', ?, '10:00', '14 Hobart Rd, Bryanston'),
                ('sch_test_02', ?, 'Solar Inverter Diagnostic', ?, '14:30', '52 West Road South, Morningside')
            """,
            (business_id, today, business_id, today),
        )

        conn.commit()

    print("=" * 60)
    print("Test data successfully loaded into database!")
    print(f"• Business WhatsApp Line: +{business_whatsapp}")
    print(f"• Owner / Escalation Line: +{owner_phone}")
    print(f"• Products Loaded: {len(products)}")
    print(f"• Sample appointments created for today ({today})")
    print("=" * 60)


if __name__ == "__main__":
    seed_database()
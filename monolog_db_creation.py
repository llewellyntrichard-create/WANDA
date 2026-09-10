import sqlite3
from pathlib import Path

DB_FILE = Path("project_monolog.db")


def seed_database():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    cursor = conn.cursor()

    # 1. Ensure schema exists
    cursor.executescript("""
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

        CREATE TABLE IF NOT EXISTS client_table (
            customer_id TEXT PRIMARY KEY,
            business_id TEXT,
            name TEXT,
            surname TEXT,
            mobile_number TEXT,
            email TEXT,
            address TEXT,
            FOREIGN KEY (business_id) REFERENCES business_info(business_id)
        );

        CREATE TABLE IF NOT EXISTS reminder_table (
            reminder_id TEXT PRIMARY KEY,
            business_id TEXT,
            detail TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (business_id) REFERENCES business_info(business_id)
        );

        CREATE TABLE IF NOT EXISTS scheduler (
            sched_id TEXT PRIMARY KEY,
            business_id TEXT,
            subject TEXT,
            date TEXT,
            time TEXT,
            location TEXT,
            FOREIGN KEY (business_id) REFERENCES business_info(business_id)
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
    """)

    biz_id = "biz_apex01"

    # 2. Insert or replace sample business details
    cursor.execute("""
        INSERT OR REPLACE INTO business_info (
            business_id, business_name, primary_mail, primary_e_mail, website, core_business
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        biz_id,
        "Apex Custom Woodworks",
        "27820001111",
        "info@apexwoodworks.co.za",
        "https://www.apexwoodworks.co.za",
        "Bespoke handcrafted hardwood furniture, home office desks, and custom cabinetry."
    ))

    # Business WhatsApp number (The incoming line/bot number)
    cursor.execute("""
        INSERT OR REPLACE INTO business_whatsapp (business_id, w_number)
        VALUES (?, ?)
    """, (biz_id, "15556765812"))

    # Owner / Manager escalation number (Used to trigger Owner Mode)
    cursor.execute("""
        INSERT OR REPLACE INTO human_escalation (business_id, man_number, response_time)
        VALUES (?, ?, ?)
    """, (biz_id, "27716850167", "within 24 business hours"))

    # Operating hours
    cursor.execute("""
        INSERT OR REPLACE INTO operating_hours (
            business_id, monday, tuesday, wednesday, thursday, friday, saturday, sunday, public_holiday
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        biz_id,
        "08:00 - 17:00",
        "08:00 - 17:00",
        "08:00 - 17:00",
        "08:00 - 17:00",
        "08:00 - 16:00",
        "09:00 - 13:00",
        "Closed",
        "Closed"
    ))

    # Location
    cursor.execute("""
        INSERT OR REPLACE INTO business_location (
            business_id, building, building_number, street, suburb, city, province
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        biz_id,
        "Timber Yard Works",
        "Unit 4B",
        "Industrial Crescent",
        "Halfway House",
        "Midrand",
        "Gauteng"
    ))

    # Service Area & Logistics
    cursor.execute("""
        INSERT OR REPLACE INTO service_area (
            business_id, service_province, service_city, service_suburb, delivery_cost
        ) VALUES (?, ?, ?, ?, ?)
    """, (
        biz_id,
        "Gauteng",
        "Johannesburg & Pretoria",
        "Midrand, Sandton, Centurion, Randburg",
        "Free delivery within 20km; R450 flat rate across greater Gauteng"
    ))

    # Products & Services
    products = [
        (
            "prod_desk01",
            biz_id,
            "Solid Oak Executive Desk",
            "Furniture",
            "per unit",
            8500.00,
            "Handcrafted 1.8m solid French oak desk with steel legs and cable grommet.",
            "10-14 working days"
        ),
        (
            "prod_shelf02",
            biz_id,
            "Floating Walnut Wall Shelf",
            "Furniture",
            "per unit",
            1250.00,
            "1.2m live-edge solid walnut wall shelf with concealed mounting brackets.",
            "3-5 working days"
        ),
        (
            "prod_serv01",
            biz_id,
            "On-site Custom Measurement & Design Consult",
            "Service",
            "per consultation",
            650.00,
            "In-person home/office consultation for custom cabinetry measurements and 3D modeling.",
            "Available on 48 hours notice"
        ),
    ]

    cursor.executemany("""
        INSERT OR REPLACE INTO product_info_detail (
            product_id, business_id, product_name, product_type, unit_measure, cost, core_business, lead_times
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, products)

    # Return Policies linked to Products
    policies = [
        ("prod_desk01", 1, "14-day defect guarantee. Custom dimension builds are non-refundable once timber is cut."),
        ("prod_shelf02", 1, "Full return or exchange within 30 days if unused and in original packaging."),
        ("prod_serv01", 0, "Consultation fees are non-refundable once an on-site visit is completed."),
    ]

    cursor.executemany("""
        INSERT OR REPLACE INTO return_policy (product_id, has_return_policy, policy)
        VALUES (?, ?, ?)
    """, policies)

    conn.commit()
    conn.close()
    print(f"Database '{DB_FILE}' initialized and seeded successfully for business_id: '{biz_id}'.")


if __name__ == "__main__":
    seed_database()
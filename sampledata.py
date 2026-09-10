import os
import sqlite3
import uuid
import datetime

DB_FILE = os.getenv("MONOLOG_DB_FILE", "monolog.db")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "109876543210987")

def generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"

def seed_data():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    biz_id = "biz_apex_plumbing_za"
    business_w_number = "27788109754"
    owner_man_number = "27716850167"

    today_str = datetime.date.today().isoformat()
    tomorrow_str = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    yesterday_str = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    print(f"[*] Seeding test data for Business ID: {biz_id}")
    print(f"[*] Inbound WhatsApp Business Line: +{business_w_number}")
    print(f"[*] Owner WhatsApp Number:          +{owner_man_number}")

    # 1. Master Business Info
    cursor.execute("""
        INSERT OR REPLACE INTO business_info 
        (business_id, business_name, primary_mail, primary_e_mail, website, core_business)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        biz_id,
        "Apex Plumb & Drain Works",
        "+27 11 450 9988",
        "service@apexplumb.co.za",
        "https://www.apexplumb.co.za",
        "Residential and commercial plumbing, geyser installations, drain unblocking, and emergency leak detection."
    ))

    # 2. Business WhatsApp Routing (Stores dedicated phone_number_id)
    cursor.execute("""
        INSERT OR REPLACE INTO business_whatsapp (business_id, w_number, phone_number_id)
        VALUES (?, ?, ?)
    """, (biz_id, business_w_number, PHONE_NUMBER_ID))

    # 3. Human Escalation (Owner Mode Authentication)
    cursor.execute("""
        INSERT OR REPLACE INTO human_escalation (business_id, man_number, response_time)
        VALUES (?, ?, ?)
    """, (biz_id, owner_man_number, "within 30 minutes"))

    # 4. Operating Hours
    cursor.execute("""
        INSERT OR REPLACE INTO operating_hours 
        (business_id, monday, tuesday, wednesday, thursday, friday, saturday, sunday, public_holiday)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        biz_id,
        "07:30 - 17:00",
        "07:30 - 17:00",
        "07:30 - 17:00",
        "07:30 - 17:00",
        "07:30 - 16:30",
        "08:00 - 13:00",
        "Closed (Emergency Callout Only)",
        "08:00 - 12:00"
    ))

    # 5. Business Physical Location (Rosebank / Johannesburg)
    cursor.execute("""
        INSERT OR REPLACE INTO business_location 
        (business_id, building, building_number, street, suburb, city, province)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        biz_id,
        "The Design District",
        "12",
        "Baker Street",
        "Rosebank",
        "Johannesburg",
        "Gauteng"
    ))

    # 6. Service Area & Delivery/Call-out Pricing
    cursor.execute("""
        INSERT OR REPLACE INTO service_area 
        (business_id, service_province, service_city, service_suburb, delivery_cost)
        VALUES (?, ?, ?, ?, ?)
    """, (
        biz_id,
        "Gauteng",
        "Johannesburg & Sandton",
        "Rosebank, Parkhurst, Greenside, Hyde Park, Craighall, Illovo, Sandhurst",
        "R350 standard call-out inspection fee (waived if repair quote accepted)"
    ))

    # 7. Products & Services Catalog + Warranties/Return Policies
    services = [
        {
            "id": "prod_drain_clear",
            "name": "High-Pressure Drain Jetting & Unblocking",
            "type": "Emergency Service",
            "unit": "per callout",
            "cost": 950.00,
            "core": "Clearing main residential lines up to 30m using high-pressure kinetic water jets.",
            "lead": "Within 2-4 hours",
            "has_policy": 1,
            "policy": "14-day clearance guarantee against recurring blockages."
        },
        {
            "id": "prod_geyser_150l",
            "name": "150L Kwikot Geyser Supply & Fit",
            "type": "Installation",
            "unit": "per complete unit",
            "cost": 8450.00,
            "core": "Complete replacement including pressure valve, drip tray, vacuum breakers, and electrical sign-off.",
            "lead": "Next-day installation",
            "has_policy": 1,
            "policy": "5-year manufacturer warranty on cylinder; 1-year warranty on workmanship and valves."
        },
        {
            "id": "prod_leak_detection",
            "name": "Acoustic Underground Leak Detection",
            "type": "Diagnostic Service",
            "unit": "per inspection",
            "cost": 1250.00,
            "core": "Electro-acoustic and tracer gas scanning to pinpoint concealed slab and garden water leaks without digging.",
            "lead": "Same-day booking available",
            "has_policy": 0,
            "policy": "Diagnostic report delivered on-site; repair quotes priced separately."
        },
        {
            "id": "prod_tap_service",
            "name": "Mixer Tap Re-seating & Washer Overhaul",
            "type": "Standard Maintenance",
            "unit": "per tap set",
            "cost": 450.00,
            "core": "Replacement of ceramic disc cartridges or rubber washers and high-pressure re-seating.",
            "lead": "Scheduled 60-min visit",
            "has_policy": 1,
            "policy": "6 months leak-free warranty on new cartridges."
        }
    ]

    for s in services:
        cursor.execute("""
            INSERT OR REPLACE INTO product_info_detail 
            (product_id, business_id, product_name, product_type, unit_measure, cost, core_business, lead_times)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (s["id"], biz_id, s["name"], s["type"], s["unit"], s["cost"], s["core"], s["lead"]))

        cursor.execute("""
            INSERT OR REPLACE INTO return_policy (product_id, has_return_policy, policy)
            VALUES (?, ?, ?)
        """, (s["id"], s["has_policy"], s["policy"]))

    # 8. Seed Customer Records (with GPS coordinates for on-site history testing)
    client_1_id = "cust_thabo_mokoena"
    client_2_id = "cust_sarah_vander"

    cursor.execute("""
        INSERT OR REPLACE INTO client_table 
        (customer_id, business_id, name, surname, mobile_number, email, address, latitude, longitude, first_contact_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        client_1_id,
        biz_id,
        "Thabo",
        "Mokoena",
        "27845551234",
        "thabo.m@gmail.com",
        "44 6th Street, Parkhurst, Johannesburg",
        -26.13880, 
        28.01620,
        "WHATSAPP_INBOUND"
    ))

    cursor.execute("""
        INSERT OR REPLACE INTO client_table 
        (customer_id, business_id, name, surname, mobile_number, email, address, latitude, longitude, first_contact_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        client_2_id,
        biz_id,
        "Sarah",
        "van der Merwe",
        "27729994321",
        "sarah.vdm@outlook.com",
        "18 Cradock Avenue, Rosebank, Johannesburg",
        -26.14640,
        28.04350,
        "WHATSAPP_INBOUND"
    ))

    # 9. Seed Completed Historical Work (For On-Site GPS & Address Lookup)
    cursor.execute("""
        INSERT OR REPLACE INTO customer_appointments
        (appointment_id, business_id, customer_id, subject, appointment_date, start_time, end_time, location, latitude, longitude, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        generate_id("apt"),
        biz_id,
        client_1_id,
        "Main sewer line tree root intrusion clearing",
        yesterday_str,
        "10:00",
        "11:00",
        "44 6th Street, Parkhurst",
        -26.13880,
        28.01620,
        "COMPLETED",
        "Cleared 15m clay pipe run with mechanical root cutter. Poured copper sulphate treatment. Advised client pipe relining will be needed if root ingress recurs in 6 months."
    ))

    # 10. Seed Today's Pending Appointments & Active Reminders (For 09:00 SAST Morning Digest)
    cursor.execute("""
        INSERT OR REPLACE INTO customer_appointments
        (appointment_id, business_id, customer_id, subject, appointment_date, start_time, end_time, location, latitude, longitude, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        generate_id("apt"),
        biz_id,
        client_2_id,
        "Solar Geyser Thermostat Inspection",
        today_str,
        "11:30",
        "12:30",
        "18 Cradock Avenue, Rosebank",
        -26.14640,
        28.04350,
        "CONFIRMED",
        "Customer reports water heating intermittently during morning hours."
    ))

    cursor.execute("""
        INSERT OR REPLACE INTO reminder_table (reminder_id, business_id, detail)
        VALUES (?, ?, ?)
    """, (generate_id("rem"), biz_id, "Order 2x 150L 400kPa Kwikot safety relief valves from Plumblink Randburg"))

    cursor.execute("""
        INSERT OR REPLACE INTO reminder_table (reminder_id, business_id, detail)
        VALUES (?, ?, ?)
    """, (generate_id("rem"), biz_id, "Issue Certificate of Compliance (CoC) for Thabo Mokoena in Parkhurst"))

    # 11. Public Promotional Event (Trade Show / Expo)
    cursor.execute("""
        INSERT OR REPLACE INTO business_events
        (event_id, business_id, event_name, start_date, end_date, start_time, end_time, venue_address, ticket_fee, description, owner_attending)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        generate_id("evt"),
        biz_id,
        "JHB Home Renovation & Green Living Expo 2026",
        tomorrow_str,
        tomorrow_str,
        "09:00",
        "17:00",
        "Sandton Convention Centre, 161 Maude St, Sandton",
        80.00,
        "Visit Stand B14 to see live demonstrations of solar water heating conversion kits and smart greywater filtration systems.",
        1
    ))

    conn.commit()
    conn.close()

    print("\n[✓] Database seed successfully populated!")
    print(f"• Business: Apex Plumb & Drain Works")
    print(f"• Inbound Line: +{business_w_number}")
    print(f"• Owner Line:   +{owner_man_number}")
    print(f"• Test Client 1: Thabo Mokoena (+27845551234) at 44 6th Street, Parkhurst")
    print(f"• Test Client 2: Sarah van der Merwe (+27729994321) booked today at 11:30")

if __name__ == "__main__":
    seed_data()
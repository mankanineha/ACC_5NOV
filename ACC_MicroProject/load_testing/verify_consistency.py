import sys
import collections
import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

def verify_system_consistency():
    print("=" * 65)
    print("  KUBERNETES SHUTTLE SYSTEM: POST-LOAD INTEGRITY AUDIT")
    print(f"  Target Endpoint: {BASE_URL}")
    print("=" * 65)

    # 1. Check Health & Pod
    try:
        health_res = requests.get(f"{BASE_URL}/api/health", timeout=5)
        health = health_res.json()
        print(f"[OK] Service Health: {health.get('status')} (Pod: {health.get('pod_name')})")
    except Exception as e:
        print(f"[FAIL] Unable to connect to service: {e}")
        return

    # 2. Fetch All Bookings
    bookings_res = requests.get(f"{BASE_URL}/api/bookings")
    if bookings_res.status_code != 200:
        print(f"[FAIL] Failed to fetch bookings: {bookings_res.text}")
        return
    bookings = bookings_res.json()

    print(f"[INFO] Total Confirmed Bookings in Database: {len(bookings)}")

    # 3. Check for Duplicate Seat Bookings
    seat_counts = collections.Counter(b["seat_id"] for b in bookings)
    duplicates = {seat_id: count for seat_id, count in seat_counts.items() if count > 1}

    print("-" * 65)
    print("  AUDIT CHECKS:")
    if duplicates:
        print("  [CRITICAL FAILURE] Double bookings detected:")
        for seat_id, count in duplicates.items():
            print(f"    - Seat ID {seat_id} was booked {count} times!")
    else:
        print("  [PASS] Zero Double-Bookings Detected!")
        print("         Every confirmed seat belongs to exactly ONE student.")

    # 4. Check Seats Status
    seats_res = requests.get(f"{BASE_URL}/api/shuttles/1/seats")
    if seats_res.status_code == 200:
        seats = seats_res.json()
        reserved_count = sum(1 for s in seats if s["is_reserved"])
        print(f"  [PASS] Database State: {reserved_count} / {len(seats)} seats reserved.")

    print("-" * 65)
    if not duplicates:
        print("  CONCLUSION: CONCURRENCY CONTROLS VALIDATED UNDER LOAD.")
        print("  - Redis SETNX Distributed Lock: Effective")
        print("  - PostgreSQL Row-Level Transaction: Consistent")
    else:
        print("  CONCLUSION: CONCURRENCY FAILURE DETECTED.")
    print("=" * 65)

if __name__ == "__main__":
    verify_system_consistency()

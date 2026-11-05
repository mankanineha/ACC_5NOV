import asyncio
import httpx
import sys

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

STUDENTS = [
    {"id": "21BCE1042", "name": "Aarav Sharma"},
    {"id": "21BCE1098", "name": "Sneha Patel"},
    {"id": "21BCE1154", "name": "Rohan Gupta"},
    {"id": "21BCE1201", "name": "Ananya Iyer"},
    {"id": "21BCE1280", "name": "Vikram Malhotra"},
    {"id": "21BCE1345", "name": "Pooja Reddy"},
    {"id": "21BCE1410", "name": "Aditya Kulkarni"},
    {"id": "21BCE1490", "name": "Meera Nambiar"},
]

async def race_for_seat(client, student, target_seat_id):
    url = f"{BASE_URL}/api/book"
    payload = {
        "seat_id": target_seat_id,
        "student_id": student["id"],
        "student_name": student["name"]
    }
    try:
        response = await client.post(url, json=payload, timeout=10.0)
        return student, response.status_code, response.json()
    except Exception as e:
        return student, 500, {"error": str(e)}

async def run_race_demo(target_seat_id=3): # Seat 1C (ID 3)
    print("=" * 72)
    print(" 🏎️  KUBERNETES CONCURRENCY RACE DEMONSTRATION")
    print(f" Target: 8 Students simultaneously racing for Seat ID {target_seat_id}")
    print("=" * 72)

    async with httpx.AsyncClient() as client:
        # Fire all 8 booking requests at the EXACT same millisecond
        tasks = [race_for_seat(client, student, target_seat_id) for student in STUDENTS]
        results = await asyncio.gather(*tasks)

    print(f"{'Student ID':<12} | {'Passenger Name':<18} | {'HTTP Code':<10} | {'Outcome'}")
    print("-" * 72)

    success_count = 0
    conflict_count = 0

    for student, status_code, data in results:
        if status_code == 201:
            success_count += 1
            ref = data.get("booking_reference", "CONFIRMED")
            outcome = f"✅ BOOKED ({ref})"
        elif status_code == 409:
            conflict_count += 1
            outcome = "⛔ REJECTED (HTTP 409 Conflict)"
        else:
            outcome = f"❌ ERROR ({status_code})"

        print(f"{student['id']:<12} | {student['name']:<18} | {status_code:<10} | {outcome}")

    print("-" * 72)
    print(f" Summary: {success_count} Winner (201 Created) | {conflict_count} Blocked (409 Conflict)")
    if success_count == 1:
        print(" 🎯 CONCURRENCY SAFETY VERIFIED: Zero Double-Bookings!")
    print("=" * 72)

if __name__ == "__main__":
    seat_id = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    asyncio.run(run_race_demo(seat_id))

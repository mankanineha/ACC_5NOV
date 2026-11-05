import random
from locust import HttpUser, task, between

class StudentRushUser(HttpUser):
    """
    Simulates students during the 8:00 AM rush hour attempting
    to book seats on the campus shuttle simultaneously.
    """
    wait_time = between(0.1, 0.5)  # Aggressive thundering herd behavior

    def on_start(self):
        self.student_id = f"STU-{random.randint(1000, 9999)}"
        self.student_name = f"Student_{self.student_id}"
        # Everyone competes for Shuttle 1 (which has 24 seats)
        self.shuttle_id = 1

    @task(3)
    def view_seats(self):
        """Simulate student opening the live seat grid."""
        self.client.get(f"/api/shuttles/{self.shuttle_id}/seats", name="/api/shuttles/[id]/seats")

    @task(5)
    def attempt_rush_booking(self):
        """
        Simulate all students rushing to book the same high-demand seats (Seats 1 to 24).
        Expectation:
        - Exactly 1 student gets HTTP 201 Created per seat.
        - All subsequent students receive HTTP 409 Conflict in < 5ms.
        - ZERO HTTP 500 errors.
        """
        target_seat_id = random.randint(1, 24)

        payload = {
            "seat_id": target_seat_id,
            "student_id": self.student_id,
            "student_name": self.student_name
        }

        with self.client.post("/api/book", json=payload, catch_response=True, name="/api/book") as response:
            if response.status_code == 201:
                # Successfully booked the seat!
                response.success()
            elif response.status_code == 409:
                # Expected concurrency rejection (seat taken or locked)
                response.success()
            else:
                # Unexpected failure (e.g. 500 Internal Server Error)
                response.failure(f"Unexpected status code {response.status_code}: {response.text}")

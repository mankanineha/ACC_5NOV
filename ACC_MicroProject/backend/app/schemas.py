from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

class RouteSchema(BaseModel):
    id: int
    source: str
    destination: str
    departure_time: str

    class Config:
        from_attributes = True


class ShuttleSchema(BaseModel):
    id: int
    route_id: int
    vehicle_number: str
    capacity: int
    status: str

    class Config:
        from_attributes = True


class SeatSchema(BaseModel):
    id: int
    shuttle_id: int
    seat_number: str
    is_reserved: bool
    is_locked: bool = False
    locked_by: Optional[str] = None
    lock_ttl_remaining: int = 0

    class Config:
        from_attributes = True


class BookingRequest(BaseModel):
    seat_id: int
    student_id: str = Field(..., min_length=2, max_length=50)
    student_name: str = Field(..., min_length=2, max_length=100)


class BookingResponse(BaseModel):
    booking_reference: str
    seat_id: int
    seat_number: str
    student_id: str
    student_name: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class LockRequest(BaseModel):
    seat_id: int
    student_id: str


class LockResponse(BaseModel):
    success: bool
    seat_id: int
    message: str
    expires_in_seconds: int = 30


class HealthResponse(BaseModel):
    status: str
    pod_name: str
    pod_ip: str
    database_connected: bool
    redis_connected: bool


class SystemStatsResponse(BaseModel):
    total_routes: int
    total_shuttles: int
    total_seats: int
    booked_seats: int
    available_seats: int
    locked_seats: int

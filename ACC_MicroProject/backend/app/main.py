import os
import uuid
import socket
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from prometheus_fastapi_instrumentator import Instrumentator

from .database import engine, Base, get_db
from .models import Route, Shuttle, Seat, Booking
from .schemas import (
    RouteSchema,
    ShuttleSchema,
    SeatSchema,
    BookingRequest,
    BookingResponse,
    LockRequest,
    LockResponse,
    HealthResponse,
    SystemStatsResponse,
)
from .redis_client import (
    acquire_seat_lock,
    release_seat_lock,
    get_seat_lock_info,
    clear_all_locks,
    get_redis_client,
    close_redis_client,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shuttle_api")

POD_NAME = os.getenv("POD_NAME", socket.gethostname())
POD_IP = os.getenv("POD_IP", "127.0.0.1")


def seed_database(db: Session):
    """Seed initial shuttle routes and seats if empty."""
    if db.query(Route).count() == 0:
        logger.info("Database is empty. Seeding initial shuttle schedule...")
        
        # Route 1: Morning Rush
        r1 = Route(
            source="Hostel Complex (Block 1-5)",
            destination="Main Academic Block",
            departure_time="08:30 AM"
        )
        # Route 2: Transit Connect
        r2 = Route(
            source="Central Library / Food Court",
            destination="Metro Transit Station",
            departure_time="05:15 PM"
        )
        db.add_all([r1, r2])
        db.commit()
        db.refresh(r1)
        db.refresh(r2)

        # Shuttle 1 for Morning Rush (24 seats)
        s1 = Shuttle(
            route_id=r1.id,
            vehicle_number="CAMPUS-EXPRESS-01",
            capacity=24,
            status="BOARDING"
        )
        # Shuttle 2 for Transit (24 seats)
        s2 = Shuttle(
            route_id=r2.id,
            vehicle_number="METRO-SHUTTLE-02",
            capacity=24,
            status="SCHEDULED"
        )
        db.add_all([s1, s2])
        db.commit()
        db.refresh(s1)
        db.refresh(s2)

        # Seed Seats for both shuttles (e.g. 1A, 1B, 1C, 1D ... 6D)
        for s in [s1, s2]:
            seat_rows = ["A", "B", "C", "D"]
            for row_idx in range(1, 7):
                for seat_letter in seat_rows:
                    seat_num = f"{row_idx}{seat_letter}"
                    seat = Seat(shuttle_id=s.id, seat_number=seat_num, is_reserved=False)
                    db.add(seat)
        db.commit()
        logger.info("Database seeding completed with 2 routes and 48 seats.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        seed_database(db)
    finally:
        db.close()
    yield
    # Cleanup Redis connection
    await close_redis_client()


app = FastAPI(
    title="Campus Shuttle Concurrency & Seat Booking API",
    description="High-concurrency microservice with Redis distributed locking and Kubernetes autoscaling",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for web UI access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus Metric Exporter
instrumentator = Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics", "/api/health"]
)
instrumentator.instrument(app).expose(app, endpoint="/metrics")


@app.get("/")
async def root():
    return {
        "status": "healthy",
        "service": "campus-shuttle-backend",
        "docs": "/docs",
        "health": "/api/health",
        "pod": POD_NAME,
        "pod_ip": POD_IP
    }


@app.get("/api/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)):
    db_ok = False
    redis_ok = False
    
    # Check DB
    try:
        db.execute(Base.metadata.tables["routes"].select().limit(1))
        db_ok = True
    except Exception as e:
        logger.error(f"Health DB error: {e}")

    # Check Redis
    try:
        r = await get_redis_client()
        redis_ok = await r.ping()
    except Exception as e:
        logger.error(f"Health Redis error: {e}")

    return HealthResponse(
        status="UP" if (db_ok and redis_ok) else "DEGRADED",
        pod_name=POD_NAME,
        pod_ip=POD_IP,
        database_connected=db_ok,
        redis_connected=redis_ok
    )


@app.get("/api/stats", response_model=SystemStatsResponse)
def get_system_stats(db: Session = Depends(get_db)):
    total_routes = db.query(Route).count()
    total_shuttles = db.query(Shuttle).count()
    total_seats = db.query(Seat).count()
    booked_seats = db.query(Seat).filter(Seat.is_reserved == True).count()
    
    return SystemStatsResponse(
        total_routes=total_routes,
        total_shuttles=total_shuttles,
        total_seats=total_seats,
        booked_seats=booked_seats,
        available_seats=total_seats - booked_seats,
        locked_seats=0  # Dynamic Redis locks can also be queried
    )


@app.get("/api/routes", response_model=List[RouteSchema])
def list_routes(db: Session = Depends(get_db)):
    return db.query(Route).all()


@app.get("/api/shuttles", response_model=List[ShuttleSchema])
def list_shuttles(route_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Shuttle)
    if route_id:
        query = query.filter(Shuttle.route_id == route_id)
    return query.all()


@app.get("/api/shuttles/{shuttle_id}/seats", response_model=List[SeatSchema])
async def get_shuttle_seats(shuttle_id: int, db: Session = Depends(get_db)):
    seats = db.query(Seat).filter(Seat.shuttle_id == shuttle_id).order_by(Seat.id).all()
    if not seats:
        raise HTTPException(status_code=404, detail="Shuttle not found or has no seats")

    seat_responses = []
    for seat in seats:
        # Check active distributed lock in Redis
        is_locked, locked_by, ttl_left = await get_seat_lock_info(seat.id)
        
        seat_responses.append(
            SeatSchema(
                id=seat.id,
                shuttle_id=seat.shuttle_id,
                seat_number=seat.seat_number,
                is_reserved=seat.is_reserved,
                is_locked=is_locked,
                locked_by=locked_by,
                lock_ttl_remaining=ttl_left
            )
        )
    return seat_responses


@app.post("/api/seats/lock", response_model=LockResponse)
async def lock_seat(request: LockRequest, db: Session = Depends(get_db)):
    """
    Attempt to acquire a 30s atomic provisional lock via Redis SETNX.
    Rejects immediately with HTTP 409 Conflict if another student holds it.
    """
    # 1. Fast DB check: Is it already permanently booked?
    seat = db.query(Seat).filter(Seat.id == request.seat_id).first()
    if not seat:
        raise HTTPException(status_code=404, detail="Seat not found")
    if seat.is_reserved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Seat {seat.seat_number} is already permanently booked"
        )

    # 2. In-Memory Atomic Lock via Redis SETNX
    success, message = await acquire_seat_lock(request.seat_id, request.student_id, ttl_seconds=30)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Lock conflict: {message}"
        )

    return LockResponse(
        success=True,
        seat_id=request.seat_id,
        message="Provisional 30-second hold acquired",
        expires_in_seconds=30
    )


@app.post("/api/seats/unlock")
async def unlock_seat(request: LockRequest):
    """Release provisional hold using Lua script."""
    released = await release_seat_lock(request.seat_id, request.student_id)
    return {"success": released, "seat_id": request.seat_id}


@app.post("/api/book", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def confirm_booking(request: BookingRequest, db: Session = Depends(get_db)):
    """
    Finalize seat booking:
    1. Verify or acquire Redis atomic lock.
    2. Commit transaction to PostgreSQL with row-level lock and unique constraint.
    3. Release lock.
    """
    seat_id = request.seat_id
    student_id = request.student_id
    student_name = request.student_name

    # Check / Acquire Redis lock first to protect database from thundering herd
    lock_ok, lock_msg = await acquire_seat_lock(seat_id, student_id, ttl_seconds=10)
    if not lock_ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Booking rejected: {lock_msg}"
        )

    try:
        # Atomic DB operation with row lock
        seat = db.query(Seat).with_for_update().filter(Seat.id == seat_id).first()
        if not seat:
            await release_seat_lock(seat_id, student_id)
            raise HTTPException(status_code=404, detail="Seat not found")

        if seat.is_reserved:
            await release_seat_lock(seat_id, student_id)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Seat {seat.seat_number} is already reserved by another student"
            )

        # Create persistent booking
        ref_code = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        booking = Booking(
            seat_id=seat.id,
            student_id=student_id,
            student_name=student_name,
            booking_reference=ref_code,
            status="CONFIRMED"
        )
        seat.is_reserved = True
        
        db.add(booking)
        db.commit()
        db.refresh(booking)

        # Release provisional lock once safely committed to DB
        await release_seat_lock(seat_id, student_id)

        logger.info(f"[BOOKING_CONFIRMED] Ref: {ref_code} | Seat: {seat.seat_number} | Student: {student_id} on Pod: {POD_NAME}")

        return BookingResponse(
            booking_reference=booking.booking_reference,
            seat_id=seat.id,
            seat_number=seat.seat_number,
            student_id=booking.student_id,
            student_name=booking.student_name,
            status=booking.status,
            created_at=booking.created_at
        )

    except (IntegrityError, Exception) as e:
        db.rollback()
        await release_seat_lock(seat_id, student_id)
        logger.warning(f"Booking conflict handled: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Seat booking conflict prevented: {str(e)}"
        )


@app.get("/api/bookings", response_model=List[BookingResponse])
def list_bookings(db: Session = Depends(get_db)):
    """Fetch all confirmed bookings for audit and demo verification."""
    bookings = db.query(Booking).join(Seat).order_by(Booking.id.desc()).all()
    results = []
    for b in bookings:
        results.append(
            BookingResponse(
                booking_reference=b.booking_reference,
                seat_id=b.seat_id,
                seat_number=b.seat.seat_number,
                student_id=b.student_id,
                student_name=b.student_name,
                status=b.status,
                created_at=b.created_at
            )
        )
    return results


@app.post("/api/admin/reset")
async def reset_demo(db: Session = Depends(get_db)):
    """Reset all seats and bookings for repeated live demonstrations."""
    await clear_all_locks()
    db.query(Booking).delete()
    db.query(Seat).update({"is_reserved": False})
    db.commit()
    logger.info("Demo reset: all bookings and locks wiped successfully.")
    return {"message": "All bookings and locks reset successfully for fresh demo."}

import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base

class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(100), nullable=False)
    destination = Column(String(100), nullable=False)
    departure_time = Column(String(20), nullable=False)

    shuttles = relationship("Shuttle", back_populates="route", cascade="all, delete-orphan")


class Shuttle(Base):
    __tablename__ = "shuttles"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    vehicle_number = Column(String(50), nullable=False)
    capacity = Column(Integer, default=24)
    status = Column(String(20), default="SCHEDULED")

    route = relationship("Route", back_populates="shuttles")
    seats = relationship("Seat", back_populates="shuttle", cascade="all, delete-orphan")


class Seat(Base):
    __tablename__ = "seats"

    id = Column(Integer, primary_key=True, index=True)
    shuttle_id = Column(Integer, ForeignKey("shuttles.id"), nullable=False)
    seat_number = Column(String(10), nullable=False)
    is_reserved = Column(Boolean, default=False)

    shuttle = relationship("Shuttle", back_populates="seats")
    booking = relationship("Booking", back_populates="seat", uselist=False)

    __table_args__ = (
        UniqueConstraint("shuttle_id", "seat_number", name="uq_shuttle_seat"),
    )


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    seat_id = Column(Integer, ForeignKey("seats.id"), nullable=False, unique=True)
    student_id = Column(String(50), nullable=False, index=True)
    student_name = Column(String(100), nullable=False)
    booking_reference = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(20), default="CONFIRMED")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    seat = relationship("Seat", back_populates="booking")

    __table_args__ = (
        UniqueConstraint("seat_id", name="uq_seat_active_booking"),
    )

from .database import Base
from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, Boolean, DateTime, ForeignKey


# ─────────────────────────────────────────────
# EXISTING MODELS (unchanged)
# ─────────────────────────────────────────────

class Guest(Base):
    __tablename__ = "guests"

    id        = Column(Integer, primary_key=True, index=True)
    room_no   = Column(Integer)
    guest_name = Column(String)
    check_in  = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    meal_plan = Column(String, nullable=True)


class TV(Base):
    __tablename__ = "tvs"

    id          = Column(Integer, primary_key=True, index=True)
    room_no     = Column(String)
    mac_address = Column(String)
    ip_address  = Column(String)
    status      = Column(String, default="UNKNOWN")
    bound       = Column(Boolean, default=False)
    bound_ip    = Column(String, nullable=True)
    bound_mac   = Column(String, nullable=True)


class Template(Base):
    __tablename__ = "templates"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String)
    theme_image = Column(String)
    description = Column(String)
    start_date  = Column(Date)
    end_date    = Column(Date)
    status      = Column(String, default="inactive")


class ActiveTheme(Base):
    __tablename__ = "active_theme"

    id          = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer)


class Activity(Base):
    __tablename__ = "activities"

    id              = Column(Integer, primary_key=True, index=True)
    title           = Column(String, nullable=False)
    time_slot       = Column(String, nullable=True)
    is_announcement = Column(Boolean, default=False)


class Service(Base):
    __tablename__ = "services"

    id        = Column(Integer, primary_key=True, index=True)
    title     = Column(String, nullable=False)
    image_url = Column(String, nullable=False)


class FoodItem(Base):
    __tablename__ = "food_items"

    id        = Column(Integer, primary_key=True, index=True)
    title     = Column(String)
    category  = Column(String)
    price     = Column(Integer)
    image_url = Column(String)


class SpaItem(Base):
    __tablename__ = "spa_items"

    id        = Column(Integer, primary_key=True, index=True)
    title     = Column(String)
    category  = Column(String)
    price     = Column(Integer, default=0)
    slot1     = Column(String)
    slot2     = Column(String, nullable=True)
    slot3     = Column(String, nullable=True)
    image_url = Column(String)


class BarItem(Base):
    __tablename__ = "bar_items"

    id        = Column(Integer, primary_key=True, index=True)
    title     = Column(String)
    category  = Column(String)
    price     = Column(Integer)
    image_url = Column(String, default="/static/images/default.jpg")


class EntertainmentItem(Base):
    __tablename__ = "entertainment_items"

    id        = Column(Integer, primary_key=True, index=True)
    title     = Column(String)
    category  = Column(String)
    price     = Column(Integer, default=0)
    venue     = Column(String, nullable=True)
    slot1     = Column(String, nullable=True)
    slot2     = Column(String, nullable=True)
    slot3     = Column(String, nullable=True)
    image_url = Column(String, default="/static/images/default.jpg")


class DineItem(Base):
    __tablename__ = "dine_items"

    id          = Column(Integer, primary_key=True, index=True)
    title       = Column(String)
    occasion    = Column(String)
    slot1       = Column(String, nullable=True)
    slot2       = Column(String, nullable=True)
    slot3       = Column(String, nullable=True)
    description = Column(String, nullable=True)
    image_url   = Column(String, default="/static/images/default.jpg")


# ─────────────────────────────────────────────
# NEW BOOKING / ORDER MODELS
# ─────────────────────────────────────────────

class Order(Base):
    """
    Stores food and bar orders placed from the TV page.
    Each row is one order session (a guest may order multiple items at once).
    The 'items' column stores a JSON string of the cart.
    For billing, use the 'total' column directly.
    """
    __tablename__ = "orders"

    id         = Column(Integer, primary_key=True, index=True)
    room_no    = Column(Integer, nullable=False, index=True)
    guest_name = Column(String, nullable=True)          # filled from Guest table at order time
    items      = Column(String, nullable=False)          # JSON string: [{id, name, qty, price}, ...]
    total      = Column(Integer, nullable=False)         # total in rupees
    order_type = Column(String, default="food")          # "food" | "bar"
    status     = Column(String, default="pending")       # pending | confirmed | delivered | cancelled
    ordered_at = Column(DateTime, default=datetime.now)
    group_id = Column(Integer, ForeignKey("group_bookings.id"), nullable=True)


class SpaBooking(Base):
    """
    Stores spa & wellness slot bookings from the TV page.
    """
    __tablename__ = "spa_bookings"

    id         = Column(Integer, primary_key=True, index=True)
    room_no    = Column(Integer, nullable=False, index=True)
    guest_name = Column(String, nullable=True)
    item_id    = Column(Integer, nullable=True)          # references spa_items.id (soft FK)
    item_title = Column(String, nullable=False)
    category   = Column(String, nullable=True)           # massage / facial / body / other
    slot       = Column(String, nullable=False)
    price      = Column(Integer, default=0)             # e.g. "09:00 AM – 10:00 AM"
    status     = Column(String, default="pending")       # pending | confirmed | completed | cancelled
    booked_at  = Column(DateTime, default=datetime.now)
    group_id = Column(Integer, ForeignKey("group_bookings.id"), nullable=True)


class EntertainmentBooking(Base):
    """
    Stores entertainment & activity slot bookings from the TV page.
    """
    __tablename__ = "entertainment_bookings"

    id         = Column(Integer, primary_key=True, index=True)
    room_no    = Column(Integer, nullable=False, index=True)
    guest_name = Column(String, nullable=True)
    item_id    = Column(Integer, nullable=True)
    item_title = Column(String, nullable=False)
    category   = Column(String, nullable=True)           # indoor / outdoor / water / kids / night
    venue      = Column(String, nullable=True)
    slot       = Column(String, nullable=False)
    guests_count = Column(Integer, default=1)
    price      = Column(Integer, default=0)              # total price (price_per_person × guests)
    status     = Column(String, default="pending")
    booked_at  = Column(DateTime, default=datetime.now)
    group_id = Column(Integer, ForeignKey("group_bookings.id"), nullable=True)


class ActivityBooking(Base):
    """
    Stores general activity/schedule reservations from the TV page.
    """
    __tablename__ = "activity_bookings"

    id          = Column(Integer, primary_key=True, index=True)
    room_no     = Column(Integer, nullable=False, index=True)
    guest_name  = Column(String, nullable=True)
    activity_id = Column(Integer, nullable=True)         # references activities.id (soft FK)
    title       = Column(String, nullable=False)
    time_slot   = Column(String, nullable=True)
    status      = Column(String, default="pending")
    booked_at   = Column(DateTime, default=datetime.now)
    group_id = Column(Integer, ForeignKey("group_bookings.id"), nullable=True)


class DineBooking(Base):
    """
    Stores fine dining / special occasion reservations from the TV page.
    """
    __tablename__ = "dine_bookings"

    id         = Column(Integer, primary_key=True, index=True)
    room_no    = Column(Integer, nullable=False, index=True)
    guest_name = Column(String, nullable=True)
    item_id    = Column(Integer, nullable=True)
    item_title = Column(String, nullable=False)
    occasion   = Column(String, nullable=True)           # romantic / birthday / anniversary / etc.
    slot       = Column(String, nullable=False)
    status     = Column(String, default="pending")
    booked_at  = Column(DateTime, default=datetime.now)
    group_id = Column(Integer, ForeignKey("group_bookings.id"), nullable=True)

class RoomServiceItem(Base):
    __tablename__ = "room_service_items"
    id          = Column(Integer, primary_key=True, index=True)
    title       = Column(String)          # e.g. "Room Cleaning"
    description = Column(String, nullable=True)
    icon        = Column(String, nullable=True)   # emoji or icon name
    image_url   = Column(String, nullable=True)
    is_active   = Column(Boolean, default=True)

class RoomServiceRequest(Base):
     __tablename__ = "room_service_requests"
     id          = Column(Integer, primary_key=True, index=True)
     room_no     = Column(Integer)
     service_id  = Column(Integer)
     service_title = Column(String)
     note        = Column(String, nullable=True)   # guest's optional note
     status      = Column(String, default="pending")   # pending / in-progress / done
     created_at  = Column(DateTime, default=datetime.now)

class GalleryItem(Base):
    __tablename__ = "gallery_items"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    description = Column(String)
    image_url = Column(String)

class GroupBooking(Base):
    __tablename__ = "group_bookings"

    id              = Column(Integer, primary_key=True)
    group_name      = Column(String(150))
    welcome_message = Column(String(300))
    room_numbers    = Column(String)
    check_in        = Column(String(20))
    check_out       = Column(String(20))
    is_active       = Column(Integer)
    created_at      = Column(String(30))
    meal_plan       = Column(String(20), nullable=True)
from datetime import datetime, date, timedelta
from math import radians, sin, cos, sqrt, atan2
from app.models import (db, Booking, Vehicle, Driver, Trailer, FleetAssignment,
                        MaintenanceRecord, SupplierPlanningSettings)

ACTIVE = {"Pending Dispatch", "Confirmed", "Driver Assigned", "Collected", "In Transit", "Approaching Destination"}

CITY_COORDS = {
    "durban": (-29.8587, 31.0218), "johannesburg": (-26.2041, 28.0473),
    "joburg": (-26.2041, 28.0473), "pretoria": (-25.7479, 28.2293),
    "cape town": (-33.9249, 18.4241), "bloemfontein": (-29.0852, 26.1596),
    "gqeberha": (-33.9608, 25.6022), "port elizabeth": (-33.9608, 25.6022),
    "polokwane": (-23.9045, 29.4689), "pietermaritzburg": (-29.6006, 30.3794),
}

def haversine_coords(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2): return None
    r=6371; dlat=radians(lat2-lat1); dlng=radians(lng2-lng1)
    x=sin(dlat/2)**2+cos(radians(lat1))*cos(radians(lat2))*sin(dlng/2)**2
    return round(2*r*atan2(sqrt(x),sqrt(1-x)), 1)

def city_coords(city):
    return CITY_COORDS.get((city or '').strip().lower())

def distance_km(a, b):
    p1, p2 = city_coords(a), city_coords(b)
    if not p1 or not p2: return None
    return round(haversine_coords(p1[0], p1[1], p2[0], p2[1]))

def assignment_dropoff_coords(assignment):
    if assignment.dropoff_lat is not None and assignment.dropoff_lng is not None:
        return assignment.dropoff_lat, assignment.dropoff_lng
    if assignment.booking and assignment.booking.delivery_lat is not None and assignment.booking.delivery_lng is not None:
        return assignment.booking.delivery_lat, assignment.booking.delivery_lng
    return city_coords(assignment.projected_city or assignment.destination_city)

def booking_collection_coords(booking):
    if booking.collection_lat is not None and booking.collection_lng is not None:
        return booking.collection_lat, booking.collection_lng
    return city_coords(booking.collection_city)

def ensure_settings(supplier):
    s = SupplierPlanningSettings.query.filter_by(supplier_id=supplier.id).first()
    if not s:
        s = SupplierPlanningSettings(supplier_id=supplier.id, home_depot_city=supplier.base_city or 'Durban')
        db.session.add(s); db.session.flush()
    return s

def compliance_ok_vehicle(v):
    return not v.roadworthy_expiry or v.roadworthy_expiry >= date.today()

def compliance_ok_driver(d):
    return ((not d.license_expiry or d.license_expiry >= date.today()) and
            (not d.pdp_expiry or d.pdp_expiry >= date.today()) and d.vetting_status != 'Rejected')

def capacity_snapshot(supplier):
    now=datetime.utcnow(); settings=ensure_settings(supplier)
    vehicles=supplier.vehicles.all(); drivers=supplier.drivers.all(); trailers=Trailer.query.filter_by(supplier_id=supplier.id).all()
    assignments=FleetAssignment.query.filter_by(supplier_id=supplier.id).all()
    active_ids={a.vehicle_id for a in assignments if a.booking and a.booking.status in ACTIVE}
    reserved_jobs=supplier.bookings.filter(Booking.status.in_(["Pending Dispatch","Confirmed"]), Booking.vehicle_id.is_(None)).count()
    maintained={m.vehicle_id for m in MaintenanceRecord.query.filter_by(supplier_id=supplier.id).filter(MaintenanceRecord.status.in_(["Scheduled","In Progress","Unsafe - blocked"])).all() if m.vehicle_id}
    blocked={v.id for v in vehicles if not compliance_ok_vehicle(v)}
    immediately=[v for v in vehicles if v.id not in active_ids|maintained|blocked and v.availability=='Available']
    active=[a for a in assignments if a.booking and a.booking.status in ACTIVE]
    route_counts={}
    for a in active:
        key=f"{a.origin_city or '-'} → {a.destination_city or '-'}"; route_counts[key]=route_counts.get(key,0)+1
    return {
      'total_horses':len(vehicles),'total_trailers':len(trailers),'total_drivers':len(drivers),
      'on_road':len(active_ids),'reserved':reserved_jobs,'maintenance':len(maintained),'compliance_blocked':len(blocked),
      'available_now':max(0,len(immediately)-reserved_jobs),'route_counts':route_counts,
      'return_gaps':[a for a in active if a.return_load_status in ('Required','Searching')],
      'assignments':active,'settings':settings,
      'usable_by_type':usable_combinations(immediately, trailers),
      'available_6h':sum(1 for a in assignments if a.available_at and now <= a.available_at <= now+timedelta(hours=6)),
      'available_24h':sum(1 for a in assignments if a.available_at and now <= a.available_at <= now+timedelta(hours=24)),
      'unassigned_jobs':supplier.bookings.filter(Booking.status.in_(["Pending Dispatch","Confirmed"]), Booking.driver_id.is_(None)).all()
    }

def usable_combinations(vehicles, trailers):
    result={}
    free=[t for t in trailers if t.status=='Available']
    for t in free: result[t.trailer_type]=result.get(t.trailer_type,0)+1
    result['Horse only']=len(vehicles)
    for k in list(result): result[k]=min(result[k],len(vehicles)) if k!='Horse only' else result[k]
    return result

def return_load_matches(supplier, assignment):
    """Find next jobs for one specific truck within radius of its projected drop-off."""
    settings=ensure_settings(supplier)
    available=assignment.available_at or datetime.utcnow()
    origin=assignment_dropoff_coords(assignment)
    if not origin:
        return []
    already_reserved={a.next_booking_id for a in FleetAssignment.query.filter(FleetAssignment.next_booking_id.isnot(None)).all()}
    q=Booking.query.filter(Booking.status.in_(["Pending Quotes","Quotes Received"]))
    matches=[]
    for b in q.all():
        if b.id == assignment.booking_id or b.id in already_reserved:
            continue
        pickup=booking_collection_coords(b)
        if not pickup:
            continue
        d=haversine_coords(origin[0],origin[1],pickup[0],pickup[1])
        if d is None or d > settings.return_load_radius_km:
            continue
        # Collection must be on/after the truck is available. Date-only jobs use start of day.
        if b.collection_date:
            collection_at=datetime.combine(b.collection_date, datetime.min.time())
            if collection_at < available - timedelta(hours=2):
                continue
        # Check payload and equipment for this exact truck/trailer combination.
        payload_ton=(b.total_weight_kg or 0)/1000
        capacity=(assignment.trailer.payload_ton if assignment.trailer else assignment.vehicle.payload_ton) or 0
        if capacity and payload_ton > capacity:
            continue
        required=(b.vehicle_type_req or '').lower().strip()
        equipment=' '.join(filter(None,[(assignment.trailer.trailer_type if assignment.trailer else ''),assignment.vehicle.vehicle_type or ''])).lower()
        equipment_match=(not required or required in equipment or any(token in equipment for token in required.split()))
        if required and not equipment_match:
            continue
        home=distance_km(b.delivery_city, settings.home_depot_city)
        score=max(0,100-(d/settings.return_load_radius_km)*40)
        if home is not None:
            score += max(0,35-(home/1500)*35)
        if equipment_match:
            score += 15
        matches.append({
            'booking':b,'collection_distance':round(d,1),'home_distance':home,
            'score':min(100,round(score)),'available_at':available,
            'dropoff_lat':origin[0],'dropoff_lng':origin[1],
            'pickup_lat':pickup[0],'pickup_lng':pickup[1],
            'radius_km':settings.return_load_radius_km,
        })
    return sorted(matches,key=lambda x:(-x['score'],x['collection_distance']))


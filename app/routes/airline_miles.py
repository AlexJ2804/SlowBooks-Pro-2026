"""Household airline miles tracker — phase 1.5 task 2.



Endpoints:

- GET    /api/airline-miles                     full page payload (programs + memberships + latest balance)

- GET    /api/airline-miles/programs            flat list of programs (for dropdowns)

- POST   /api/airline-miles/memberships         create new (program, person) membership

- PATCH  /api/airline-miles/memberships/{id}    edit member#/elite/notes

- DELETE /api/airline-miles/memberships/{id}    remove a membership (cascades snapshots)

- POST   /api/airline-miles/snapshots           upsert balance for (membership_id, as_of_date)

- GET    /api/airline-miles/memberships/{id}/snapshots  history for one membership



The main GET is shaped for the page render: one query per table,

joined in Python so the response carries the latest snapshot per

membership flattened onto the membership row. Avoids N+1 round-trips

to the latest-snapshot subquery for each membership.



POST snapshots is upsert by (membership_id, as_of_date), same pattern

as /api/balances — re-entering today's value overwrites instead of

forcing a delete-first dance.

"""

from collections import defaultdict

from typing import Optional



from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy import func

from sqlalchemy.orm import Session



from app.database import get_db

from app.models.airline_miles import (

    AirlineMilesSnapshot, AirlineProgram, AirlineProgramMembership,

)

from app.models.people import Person

from app.schemas.airline_miles import (

    AirlineProgramCreate, AirlineProgramResponse, MembershipCreate,

    MembershipRow, MembershipUpdate, ProgramWithMemberships,

    SnapshotCreate, SnapshotResponse,

)





router = APIRouter(prefix="/api/airline-miles", tags=["airline-miles"])





# ---------------------------------------------------------------------

# Programs

# ---------------------------------------------------------------------

@router.get("/programs", response_model=list[AirlineProgramResponse])

def list_programs(db: Session = Depends(get_db)):

    return (

        db.query(AirlineProgram)

        .order_by(AirlineProgram.display_order, AirlineProgram.name)

        .all()

    )





@router.post("/programs", response_model=AirlineProgramResponse, status_code=201)

def create_program(data: AirlineProgramCreate, db: Session = Depends(get_db)):

    if data.alliance not in {"oneworld", "star", "skyteam", "none"}:

        raise HTTPException(status_code=422, detail="Invalid alliance value")

    existing = (

        db.query(AirlineProgram).filter(AirlineProgram.code == data.code).first()

    )

    if existing is not None:

        raise HTTPException(

            status_code=409,

            detail=f"Program with code '{data.code}' already exists",

        )

    prog = AirlineProgram(**data.model_dump())

    db.add(prog)

    db.commit()

    db.refresh(prog)

    return prog





# ---------------------------------------------------------------------

# Page payload — programs with memberships and latest balance

# ---------------------------------------------------------------------

@router.get("", response_model=list[ProgramWithMemberships])

def list_page_payload(db: Session = Depends(get_db)):

    """Single round-trip for the miles page render.



    Returns every program with every membership rolled up underneath,

    each membership carrying its latest balance + as-of date. Programs

    with no memberships still appear (empty card placeholder).

    """

    programs = (

        db.query(AirlineProgram)

        .order_by(AirlineProgram.display_order, AirlineProgram.name)

        .all()

    )

    memberships = (

        db.query(AirlineProgramMembership, Person)

        .join(Person, Person.id == AirlineProgramMembership.person_id)

        .order_by(Person.display_order, Person.id)

        .all()

    )



    # Latest snapshot per membership: pick max as_of_date per group, then

    # join back to the snapshot row for its balance. One query rather

    # than per-membership lookups.

    latest_dates_subq = (

        db.query(

            AirlineMilesSnapshot.membership_id.label("mid"),

            func.max(AirlineMilesSnapshot.as_of_date).label("max_date"),

        )

        .group_by(AirlineMilesSnapshot.membership_id)

        .subquery()

    )

    latest_rows = (

        db.query(AirlineMilesSnapshot)

        .join(

            latest_dates_subq,

            (AirlineMilesSnapshot.membership_id == latest_dates_subq.c.mid)

            & (AirlineMilesSnapshot.as_of_date == latest_dates_subq.c.max_date),

        )

        .all()

    )

    latest_by_mid = {s.membership_id: s for s in latest_rows}



    rows_by_program: dict[int, list[MembershipRow]] = defaultdict(list)

    for membership, person in memberships:

        snap = latest_by_mid.get(membership.id)

        rows_by_program[membership.program_id].append(MembershipRow(

            id=membership.id,

            program_id=membership.program_id,

            person_id=membership.person_id,

            person_name=person.name,

            person_display_order=person.display_order,

            member_number=membership.member_number,

            elite_status=membership.elite_status,

            notes=membership.notes,

            latest_balance=snap.balance if snap is not None else None,

            latest_as_of_date=snap.as_of_date if snap is not None else None,

        ))



    payload: list[ProgramWithMemberships] = []

    for prog in programs:

        rows = rows_by_program.get(prog.id, [])

        total = sum((r.latest_balance or 0) for r in rows)

        payload.append(ProgramWithMemberships(

            id=prog.id,

            code=prog.code,

            name=prog.name,

            alliance=prog.alliance,

            brand_color=prog.brand_color,

            logo_path=prog.logo_path,

            display_order=prog.display_order,

            memberships=rows,

            total_balance=total,

        ))

    return payload





# ---------------------------------------------------------------------

# Memberships

# ---------------------------------------------------------------------

@router.post("/memberships", response_model=MembershipRow, status_code=201)

def create_membership(data: MembershipCreate, db: Session = Depends(get_db)):

    program = db.query(AirlineProgram).filter(AirlineProgram.id == data.program_id).first()

    if program is None:

        raise HTTPException(status_code=404, detail="Program not found")

    person = db.query(Person).filter(Person.id == data.person_id).first()

    if person is None:

        raise HTTPException(status_code=404, detail="Person not found")

    existing = (

        db.query(AirlineProgramMembership)

        .filter(

            AirlineProgramMembership.program_id == data.program_id,

            AirlineProgramMembership.person_id == data.person_id,

        )

        .first()

    )

    if existing is not None:

        raise HTTPException(

            status_code=409,

            detail="Membership already exists for this program/person",

        )

    m = AirlineProgramMembership(

        program_id=data.program_id,

        person_id=data.person_id,

        member_number=data.member_number,

        elite_status=data.elite_status,

        notes=data.notes,

    )

    db.add(m)

    db.commit()

    db.refresh(m)

    return MembershipRow(

        id=m.id,

        program_id=m.program_id,

        person_id=m.person_id,

        person_name=person.name,

        person_display_order=person.display_order,

        member_number=m.member_number,

        elite_status=m.elite_status,

        notes=m.notes,

        latest_balance=None,

        latest_as_of_date=None,

    )





@router.patch("/memberships/{membership_id}", response_model=MembershipRow)

def update_membership(

    membership_id: int, data: MembershipUpdate, db: Session = Depends(get_db),

):

    m = (

        db.query(AirlineProgramMembership)

        .filter(AirlineProgramMembership.id == membership_id)

        .first()

    )

    if m is None:

        raise HTTPException(status_code=404, detail="Membership not found")



    # Only overwrite fields the client included (model_dump exclude_unset

    # keeps untouched fields at their current values rather than nulling them).

    for k, v in data.model_dump(exclude_unset=True).items():

        setattr(m, k, v)

    db.commit()

    db.refresh(m)



    person = db.query(Person).filter(Person.id == m.person_id).first()

    latest = (

        db.query(AirlineMilesSnapshot)

        .filter(AirlineMilesSnapshot.membership_id == m.id)

        .order_by(AirlineMilesSnapshot.as_of_date.desc())

        .first()

    )

    return MembershipRow(

        id=m.id,

        program_id=m.program_id,

        person_id=m.person_id,

        person_name=person.name if person else "",

        person_display_order=person.display_order if person else 0,

        member_number=m.member_number,

        elite_status=m.elite_status,

        notes=m.notes,

        latest_balance=latest.balance if latest else None,

        latest_as_of_date=latest.as_of_date if latest else None,

    )





@router.delete("/memberships/{membership_id}")

def delete_membership(membership_id: int, db: Session = Depends(get_db)):

    m = (

        db.query(AirlineProgramMembership)

        .filter(AirlineProgramMembership.id == membership_id)

        .first()

    )

    if m is None:

        raise HTTPException(status_code=404, detail="Membership not found")

    db.delete(m)

    db.commit()

    return {"message": "Membership deleted"}





# ---------------------------------------------------------------------

# Snapshots

# ---------------------------------------------------------------------

@router.get(

    "/memberships/{membership_id}/snapshots",

    response_model=list[SnapshotResponse],

)

def list_snapshots(membership_id: int, db: Session = Depends(get_db)):

    m = (

        db.query(AirlineProgramMembership)

        .filter(AirlineProgramMembership.id == membership_id)

        .first()

    )

    if m is None:

        raise HTTPException(status_code=404, detail="Membership not found")

    return (

        db.query(AirlineMilesSnapshot)

        .filter(AirlineMilesSnapshot.membership_id == membership_id)

        .order_by(AirlineMilesSnapshot.as_of_date.desc())

        .all()

    )





@router.post("/snapshots", response_model=SnapshotResponse, status_code=201)

def upsert_snapshot(data: SnapshotCreate, db: Session = Depends(get_db)):

    m = (

        db.query(AirlineProgramMembership)

        .filter(AirlineProgramMembership.id == data.membership_id)

        .first()

    )

    if m is None:

        raise HTTPException(status_code=404, detail="Membership not found")



    existing = (

        db.query(AirlineMilesSnapshot)

        .filter(

            AirlineMilesSnapshot.membership_id == data.membership_id,

            AirlineMilesSnapshot.as_of_date == data.as_of_date,

        )

        .first()

    )

    if existing is not None:

        existing.balance = data.balance

        existing.notes = data.notes

        db.commit()

        db.refresh(existing)

        return existing



    snap = AirlineMilesSnapshot(

        membership_id=data.membership_id,

        as_of_date=data.as_of_date,

        balance=data.balance,

        notes=data.notes,

    )

    db.add(snap)

    db.commit()

    db.refresh(snap)

    return snap





@router.delete("/snapshots/{snapshot_id}")

def delete_snapshot(snapshot_id: int, db: Session = Depends(get_db)):

    snap = (

        db.query(AirlineMilesSnapshot)

        .filter(AirlineMilesSnapshot.id == snapshot_id)

        .first()

    )

    if snap is None:

        raise HTTPException(status_code=404, detail="Snapshot not found")

    db.delete(snap)

    db.commit()

    return {"message": "Snapshot deleted"}


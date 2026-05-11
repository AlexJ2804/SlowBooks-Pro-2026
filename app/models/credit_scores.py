"""Credit scores — phase 1.5 task 3.

One row per (person, bureau, score_model, as_of_date) reading. The
unique tuple includes score_model so a person can record both their
FICO 8 and their VantageScore on the same day from the same bureau
without colliding.

Role-gating (parents only) is enforced in the route handler, not on
the model — the rule needs a join into people.role and benefits from
returning a specific 422 message.
"""
from sqlalchemy import (
    CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class CreditScore(Base):
    __tablename__ = "credit_scores"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(
        Integer, ForeignKey("people.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    # Capitalized to match how the bureaus brand themselves. CHECK
    # constraint below + Pydantic enum keep raw-SQL inserts honest.
    bureau = Column(Text, nullable=False)
    score = Column(Integer, nullable=False)
    score_model = Column(
        Text, nullable=False, default="FICO 8", server_default="FICO 8",
    )
    as_of_date = Column(Date, nullable=False)
    source = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "bureau IN ('Equifax', 'Experian', 'TransUnion')",
            name="ck_credit_scores_bureau_values",
        ),
        CheckConstraint(
            "score >= 300 AND score <= 850",
            name="ck_credit_scores_score_range",
        ),
        UniqueConstraint(
            "person_id", "bureau", "score_model", "as_of_date",
            name="uq_credit_scores_person_bureau_model_date",
        ),
    )

    person = relationship("Person")

# ============================================================================
# Decompiled from qbw32.exe!CItemManager  Offset: 0x000F4E00
# Original Btrieve table: ITEM.DAT (record size 0x01C0, 4 key segments)
# Intuit called these "ItemRef" entries — the SDK exposed them through the
# IItemQuery interface. Type field was a WORD that mapped to the
# qbXMLItemTypeEnum in the QBFC COM library.
# ============================================================================

import enum

from sqlalchemy import Column, Integer, String, Enum, Boolean, Numeric, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import relationship

from app.database import Base


class ItemType(str, enum.Enum):
    # qbXMLItemTypeEnum @ 0x000F5090
    PRODUCT = "product"      # itInventory (0x00)
    SERVICE = "service"      # itService (0x01)
    MATERIAL = "material"    # itNonInventory (0x02) — we renamed this for clarity
    LABOR = "labor"          # itOtherCharge (0x03) — labor/hourly billing


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    item_type = Column(Enum(ItemType), nullable=False)
    description = Column(Text, nullable=True)
    rate = Column(Numeric(12, 2), default=0)
    cost = Column(Numeric(12, 2), default=0)
    income_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    expense_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    is_taxable = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    income_account = relationship("Account", foreign_keys=[income_account_id])
    expense_account = relationship("Account", foreign_keys=[expense_account_id])

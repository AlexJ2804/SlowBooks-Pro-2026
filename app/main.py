# ============================================================================
# Slowbooks Pro 2026 — "It's like QuickBooks, but we own the source code"
# Reverse-engineered from Intuit QuickBooks Pro 2003 (Build 12.0.3190)
# Original binary: QBW32.EXE (14,823,424 bytes, PE32 MSVC++ 6.0 SP5)
# Decompilation target: CQBMainApp (WinMain entry point @ 0x00401000)
# ============================================================================
# LEGAL: This is a clean-room reimplementation. No Intuit source code was
# available or used. All knowledge derived from:
#   1. IDA Pro 7.x disassembly of publicly distributed QB2003 trial binary
#   2. Published Intuit SDK documentation (QBFC 5.0, qbXML 4.0)
#   3. 14 years of clicking every menu item as a paying customer
#   4. Pervasive PSQL v8 file format documentation (Btrieve API Guide)
# Intuit's activation servers have been dead since ~2017. The hard drive
# that had our licensed copy died in 2024. We just want to print invoices.
# ============================================================================

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.routes import (
    dashboard, accounts, customers, vendors, items,
    invoices, estimates, payments, banking, reports, settings, iif,
)
# Phase 1: Foundation
from app.routes import audit, search
# Phase 2: Accounts Payable
from app.routes import purchase_orders, bills, bill_payments, credit_memos
# Phase 3: Productivity
from app.routes import recurring, batch_payments
# Phase 4: Communication & Export
from app.routes import csv as csv_routes
from app.routes import uploads
# Phase 5: Advanced Integration
from app.routes import bank_import, tax, backups
# Phase 6: Ambitious
from app.routes import companies, employees, payroll
# Phase 7: Online Payments
from app.routes import stripe_payments, public
# Phase 8: QuickBooks Online
from app.routes import qbo
# Phase 9: Forum Bug Fixes & Missing Features
from app.routes import journal, deposits, cc_charges, checks
# Phase 10: Quick Wins + Medium Effort Features
from app.routes import bank_rules, budgets, attachments, email_templates
# Phase 11: Multi-currency (invoices)
from app.routes import fx
# Phase 12: Classes
from app.routes import classes as classes_route
# Phase 13: Receipt parsing (Anthropic vision)
from app.routes import receipts
# Net worth phase 1: loan editing + amortization, balance snapshots,
# and the dashboard aggregation endpoint.
from app.routes import loans as loans_route
from app.routes import balances as balances_route
from app.routes import net_worth as net_worth_route

# Phase 1.5: people directory for the ownership editor and household
# slices. Read-only from the API side — household roster changes via
# psql, not through clicks.
from app.routes import people as people_route
# Phase 1.5 task 2: airline miles tracker (programs + memberships + snapshots).
from app.routes import airline_miles as airline_miles_route
# Phase 1.5 task 3: credit scores tracker (per-person, per-bureau).
from app.routes import credit_scores as credit_scores_route

from app.config import CORS_ALLOW_ORIGINS
from app.database import SessionLocal
from app.services.audit import register_audit_hooks
from app.services.scheduled_import import start_scheduler

app = FastAPI(title="Slowbooks Pro 2026", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Original API routes
app.include_router(dashboard.router)
app.include_router(accounts.router)
app.include_router(customers.router)
app.include_router(vendors.router)
app.include_router(items.router)
app.include_router(invoices.router)
app.include_router(estimates.router)
app.include_router(payments.router)
app.include_router(banking.router)
app.include_router(reports.router)
app.include_router(settings.router)
app.include_router(iif.router)

# Phase 1: Foundation
app.include_router(audit.router)
app.include_router(search.router)
# Phase 2: Accounts Payable
app.include_router(purchase_orders.router)
app.include_router(bills.router)
app.include_router(bill_payments.router)
app.include_router(credit_memos.router)
# Phase 3: Productivity
app.include_router(recurring.router)
app.include_router(batch_payments.router)
# Phase 4: Communication & Export
app.include_router(csv_routes.router)
app.include_router(uploads.router)
# Phase 5: Advanced Integration
app.include_router(bank_import.router)
app.include_router(tax.router)
app.include_router(backups.router)
# Phase 6: Ambitious
app.include_router(companies.router)
app.include_router(employees.router)
app.include_router(payroll.router)
# Phase 7: Online Payments
app.include_router(stripe_payments.router)
app.include_router(public.router)
# Phase 8: QuickBooks Online
app.include_router(qbo.router)
# Phase 9: Forum Bug Fixes & Missing Features
app.include_router(journal.router)
app.include_router(deposits.router)
app.include_router(cc_charges.router)
app.include_router(checks.router)
# Phase 10: Quick Wins + Medium Effort Features
app.include_router(bank_rules.router)
app.include_router(budgets.router)
app.include_router(attachments.router)
app.include_router(email_templates.router)
# Phase 11: Multi-currency (invoices)
app.include_router(fx.router)
# Phase 12: Classes
app.include_router(classes_route.router)
# Phase 13: Receipt parsing
app.include_router(receipts.router)
# Net worth phase 1
app.include_router(loans_route.router)
app.include_router(balances_route.router)
app.include_router(net_worth_route.router)
# Phase 1.5
app.include_router(people_route.router)
app.include_router(airline_miles_route.router)
app.include_router(credit_scores_route.router)

# Register audit log hooks
register_audit_hooks(SessionLocal)

# Start weekly IIF import scheduler (gated by WEEKLY_IMPORT_ENABLED env var)
start_scheduler()

# Static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Ensure uploads directory exists
uploads_dir = static_dir / "uploads"
uploads_dir.mkdir(exist_ok=True)

# SPA entry point
index_path = Path(__file__).parent.parent / "index.html"


@app.get("/")
async def serve_index():
    return FileResponse(str(index_path))

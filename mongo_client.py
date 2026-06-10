import os
from datetime import datetime, date, timedelta
from bson import ObjectId
from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv

load_dotenv()

_client = None


def get_db():
    global _client
    if _client is None:
        _client = MongoClient(os.getenv("MONGODB_URI"))
    return _client["aretesapiens"]


def _s(doc):
    if not doc:
        return None
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat() + "Z"
    return d


def _ss(docs):
    return [_s(d) for d in docs]


# ── Users ──────────────────────────────────────────────────────────────────────

def get_or_create_user(user_id="demo"):
    db = get_db()
    user = db.users.find_one({"user_id": user_id})
    if not user:
        db.users.insert_one({
            "user_id": user_id,
            "plan": "free",
            "trial_active": False,
            "trial_expires": None,
            "created_at": datetime.utcnow(),
        })
        user = db.users.find_one({"user_id": user_id})
    return user


def is_premium(user_id="demo"):
    user = get_or_create_user(user_id)
    if user.get("plan") == "premium":
        return True
    if user.get("trial_active") and user.get("trial_expires"):
        expires = user["trial_expires"]
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires)
        if expires > datetime.utcnow():
            return True
    return False


def activate_trial(user_id="demo"):
    db = get_db()
    get_or_create_user(user_id)
    db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "trial_active": True,
            "trial_expires": datetime.utcnow() + timedelta(days=7),
        }}
    )


# ── Legal Documents (Vaakil) ───────────────────────────────────────────────────

def save_document(session_id, country_code, doc_type, raw_text, analysis, filename=None):
    db = get_db()
    doc = {
        "session_id": session_id,
        "country_code": country_code,
        "doc_type": doc_type,
        "raw_text": raw_text[:5000],
        "analysis": analysis,
        "filename": filename,
        "created_at": datetime.utcnow(),
    }
    result = db.documents.insert_one(doc)
    return str(result.inserted_id)


def get_document(doc_id):
    return _s(get_db().documents.find_one({"_id": ObjectId(doc_id)}))


def get_session_document(session_id):
    return _s(get_db().documents.find_one({"session_id": session_id}, sort=[("created_at", DESCENDING)]))


def save_chat_message(session_id, role, content):
    get_db().chat_history.insert_one({
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": datetime.utcnow(),
    })


def get_chat_history(session_id, limit=20):
    docs = list(
        get_db().chat_history.find({"session_id": session_id})
        .sort("created_at", 1).limit(limit)
    )
    return [{"role": d["role"], "content": d["content"]} for d in docs]


# ── Jurisdictions ──────────────────────────────────────────────────────────────

def upsert_jurisdiction(country_code, data):
    get_db().jurisdictions.update_one(
        {"country_code": country_code},
        {"$set": data},
        upsert=True,
    )


def get_jurisdiction(country_code):
    return _s(get_db().jurisdictions.find_one({"country_code": country_code.upper()}))


# ── Subscriptions ──────────────────────────────────────────────────────────────

def get_subscriptions(user_id="demo"):
    return _ss(get_db().subscriptions.find({"user_id": user_id}).sort("next_renewal", 1))


def get_subscription(doc_id):
    return _s(get_db().subscriptions.find_one({"_id": ObjectId(doc_id)}))


def add_subscription(user_id, name, category, amount, currency, billing_cycle,
                     next_renewal, started_on, price_history=None, notes=""):
    get_db().subscriptions.insert_one({
        "user_id": user_id,
        "name": name,
        "category": category,
        "amount": float(amount),
        "currency": currency,
        "billing_cycle": billing_cycle,
        "next_renewal": next_renewal,
        "started_on": started_on,
        "price_history": price_history or [{"amount": float(amount), "from": started_on}],
        "notes": notes,
    })


def delete_subscription(doc_id):
    get_db().subscriptions.delete_one({"_id": ObjectId(doc_id)})


# ── Bills ──────────────────────────────────────────────────────────────────────

def get_bills(user_id="demo"):
    return _ss(get_db().bills.find({"user_id": user_id}))


def get_bill(doc_id):
    return _s(get_db().bills.find_one({"_id": ObjectId(doc_id)}))


def add_bill(user_id, name, category, history, currency="INR", alert_threshold_pct=20):
    get_db().bills.insert_one({
        "user_id": user_id,
        "name": name,
        "category": category,
        "history": history,
        "currency": currency,
        "alert_threshold_pct": float(alert_threshold_pct),
    })


def delete_bill(doc_id):
    get_db().bills.delete_one({"_id": ObjectId(doc_id)})


def add_bill_reading(doc_id, month, amount):
    get_db().bills.update_one(
        {"_id": ObjectId(doc_id)},
        {"$push": {"history": {"month": month, "amount": float(amount)}}},
    )


# ── Warranties ─────────────────────────────────────────────────────────────────

def get_warranties(user_id="demo"):
    return _ss(get_db().warranties.find({"user_id": user_id}).sort("warranty_expiry", 1))


def get_warranty(doc_id):
    return _s(get_db().warranties.find_one({"_id": ObjectId(doc_id)}))


def add_warranty(user_id, item_name, category, purchase_date, warranty_expiry,
                 purchase_price, currency="INR", notes=""):
    get_db().warranties.insert_one({
        "user_id": user_id,
        "item_name": item_name,
        "category": category,
        "purchase_date": purchase_date,
        "warranty_expiry": warranty_expiry,
        "purchase_price": float(purchase_price),
        "currency": currency,
        "notes": notes,
    })


def delete_warranty(doc_id):
    get_db().warranties.delete_one({"_id": ObjectId(doc_id)})


# ── Groceries ──────────────────────────────────────────────────────────────────

def get_groceries(user_id="demo"):
    return _ss(get_db().groceries.find({"user_id": user_id}))


def get_grocery(doc_id):
    return _s(get_db().groceries.find_one({"_id": ObjectId(doc_id)}))


def add_grocery_item(user_id, item_name, unit, price_history, currency="INR", usual_store=""):
    get_db().groceries.insert_one({
        "user_id": user_id,
        "item_name": item_name,
        "unit": unit,
        "price_history": price_history,
        "currency": currency,
        "usual_store": usual_store,
    })


def add_grocery_price(doc_id, date_iso, price):
    get_db().groceries.update_one(
        {"_id": ObjectId(doc_id)},
        {"$push": {"price_history": {"date": date_iso, "price": float(price)}}},
    )


def delete_grocery(doc_id):
    get_db().groceries.delete_one({"_id": ObjectId(doc_id)})


# ── Alerts ─────────────────────────────────────────────────────────────────────

def save_alert(user_id, module, title, body, severity, source_id=None):
    get_db().alerts.insert_one({
        "user_id": user_id,
        "module": module,
        "title": title,
        "body": body,
        "severity": severity,
        "created_at": datetime.utcnow(),
        "seen": False,
        "source_id": str(source_id) if source_id else None,
    })


def get_alerts(user_id="demo", limit=30):
    docs = list(
        get_db().alerts.find({"user_id": user_id}, {"_id": 0})
        .sort("created_at", DESCENDING).limit(limit)
    )
    for a in docs:
        if "created_at" in a and isinstance(a["created_at"], datetime):
            a["created_at"] = a["created_at"].isoformat() + "Z"
    return docs


def alert_exists_for_source(source_id, module, hours=24):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    return get_db().alerts.find_one({
        "source_id": str(source_id),
        "module": module,
        "created_at": {"$gte": cutoff},
    }) is not None


# ── Seed demo data ─────────────────────────────────────────────────────────────

def seed_demo(user_id="demo"):
    db = get_db()
    db.subscriptions.delete_many({"user_id": user_id})
    db.bills.delete_many({"user_id": user_id})
    db.warranties.delete_many({"user_id": user_id})
    db.groceries.delete_many({"user_id": user_id})
    db.alerts.delete_many({"user_id": user_id})

    # Ensure demo user exists
    get_or_create_user(user_id)

    today = date.today()

    # ── Subscriptions ──
    add_subscription(user_id, "Netflix", "streaming", 799, "INR", "monthly",
                     (today + timedelta(days=4)).isoformat(), "2023-01-01",
                     [{"amount": 649, "from": "2023-01-01"}, {"amount": 799, "from": "2025-11-01"}])
    add_subscription(user_id, "Spotify", "streaming", 119, "INR", "monthly",
                     (today + timedelta(days=18)).isoformat(), "2022-06-01",
                     [{"amount": 119, "from": "2022-06-01"}])
    add_subscription(user_id, "Amazon Prime", "other", 1499, "INR", "annual",
                     (today + timedelta(days=67)).isoformat(), "2021-03-01",
                     [{"amount": 999, "from": "2021-03-01"}, {"amount": 1499, "from": "2024-03-01"}])
    add_subscription(user_id, "iCloud 200GB", "software", 75, "INR", "monthly",
                     (today + timedelta(days=2)).isoformat(), "2020-09-01",
                     [{"amount": 75, "from": "2020-09-01"}])
    add_subscription(user_id, "Gym Membership", "fitness", 2200, "INR", "monthly",
                     (today + timedelta(days=11)).isoformat(), "2025-01-01",
                     [{"amount": 1800, "from": "2025-01-01"}, {"amount": 2200, "from": "2026-01-01"}])

    # ── Bills ──
    add_bill(user_id, "Electricity — BESCOM", "electricity",
             [{"month": "2026-01", "amount": 1840}, {"month": "2026-02", "amount": 1920},
              {"month": "2026-03", "amount": 1780}, {"month": "2026-04", "amount": 1850},
              {"month": "2026-05", "amount": 2640}])
    add_bill(user_id, "Internet — Airtel", "internet",
             [{"month": "2026-01", "amount": 999}, {"month": "2026-02", "amount": 999},
              {"month": "2026-03", "amount": 999}, {"month": "2026-04", "amount": 999},
              {"month": "2026-05", "amount": 999}])
    add_bill(user_id, "Water", "water",
             [{"month": "2026-01", "amount": 340}, {"month": "2026-02", "amount": 360},
              {"month": "2026-03", "amount": 320}, {"month": "2026-04", "amount": 380},
              {"month": "2026-05", "amount": 420}])
    add_bill(user_id, "Credit Card — HDFC", "credit_card",
             [{"month": "2026-01", "amount": 12400}, {"month": "2026-02", "amount": 18900},
              {"month": "2026-03", "amount": 14200}, {"month": "2026-04", "amount": 15800},
              {"month": "2026-05", "amount": 28400}])
    add_bill(user_id, "Piped Gas", "gas",
             [{"month": "2026-01", "amount": 682}, {"month": "2026-02", "amount": 675},
              {"month": "2026-03", "amount": 688}, {"month": "2026-04", "amount": 671},
              {"month": "2026-05", "amount": 684}])

    # ── Warranties ──
    add_warranty(user_id, 'MacBook Pro 14"', "electronics",
                 "2022-06-15", (today + timedelta(days=12)).isoformat(), 189900)
    add_warranty(user_id, "Samsung Refrigerator", "appliance",
                 "2020-04-10", (today + timedelta(days=48)).isoformat(), 52000)
    add_warranty(user_id, "iPhone 15 Pro", "electronics",
                 "2023-09-22", (today - timedelta(days=23)).isoformat(), 134900)
    add_warranty(user_id, "Washing Machine", "appliance",
                 "2024-10-05", (today + timedelta(days=240)).isoformat(), 38500)

    # ── Groceries ──
    def ph(pairs):
        return [{"date": d, "price": p} for d, p in pairs]

    add_grocery_item(user_id, "Eggs (12 pack)", "pack",
        ph([("2026-01-01", 89), ("2026-02-01", 92), ("2026-03-01", 95),
            ("2026-04-01", 98), ("2026-05-01", 115)]))
    add_grocery_item(user_id, "Atta 5kg", "kg",
        ph([("2026-01-01", 245), ("2026-02-01", 248), ("2026-03-01", 255),
            ("2026-04-01", 262), ("2026-05-01", 271)]))
    add_grocery_item(user_id, "Cooking Oil 1L", "litre",
        ph([("2026-01-01", 145), ("2026-02-01", 148), ("2026-03-01", 156),
            ("2026-04-01", 162), ("2026-05-01", 178)]))
    add_grocery_item(user_id, "Milk 1L", "litre",
        ph([("2026-01-01", 62), ("2026-02-01", 62), ("2026-03-01", 66),
            ("2026-04-01", 66), ("2026-05-01", 68)]))
    add_grocery_item(user_id, "Tomatoes 1kg", "kg",
        ph([("2026-01-01", 35), ("2026-02-01", 28), ("2026-03-01", 42),
            ("2026-04-01", 88), ("2026-05-01", 62)]))
    add_grocery_item(user_id, "Rice 5kg", "kg",
        ph([("2026-01-01", 320), ("2026-02-01", 325), ("2026-03-01", 328),
            ("2026-04-01", 335), ("2026-05-01", 342)]))

    # ── Seed demo legal document (Vaakil) ──
    demo_doc_text = """HDFC Bank Limited
Debt Recovery Notice

To: Demo User
Address: 123 MG Road, Bengaluru, Karnataka 560001

Date: 01 June 2026
Ref: Loan Account No. XXXX-XXXX-8821

Dear Sir/Madam,

This is to inform you that as per our records, the above-mentioned loan account is currently OVERDUE. The total outstanding amount as on date is Rs. 2,84,500/- (Rupees Two Lakh Eighty Four Thousand Five Hundred Only), which includes principal, interest, and applicable charges.

You are hereby given NOTICE to make payment of the entire outstanding amount within 7 (seven) days from the date of this notice, failing which the Bank shall be constrained to initiate legal proceedings against you under the SARFAESI Act, 2002, and/or Recovery of Debts and Bankruptcy Act, 1993.

Please be informed that failure to pay may result in:
1. Criminal proceedings under Section 138 of the Negotiable Instruments Act
2. Arrest and detention
3. Reporting to CIBIL affecting your credit score
4. Seizure and sale of assets

You are requested to contact our Recovery Department immediately.

For HDFC Bank Limited
Authorized Signatory
Recovery & Collections Division"""

    demo_analysis = {
        "country": "India",
        "country_code": "IN",
        "doc_type": "debt_collection",
        "doc_type_label": "Debt Recovery / Loan Notice",
        "plain_summary": "HDFC Bank is claiming you owe ₹2,84,500 on a loan account and demanding payment within 7 days. They are threatening criminal proceedings, arrest, and asset seizure.",
        "what_it_means": "This is a debt collection notice from HDFC Bank. The bank is trying to recover an overdue loan. The 7-day deadline is a pressure tactic — under the SARFAESI Act, banks must provide a mandatory 60-day notice before taking any action. This notice does not comply with that requirement.",
        "issues_found": [
            {
                "severity": "high",
                "title": "Threatening arrest for civil debt — illegal",
                "excerpt": "Arrest and detention",
                "explanation": "You cannot be arrested for failing to repay a bank loan in India. Threatening arrest for civil debt is a violation of the RBI Fair Practices Code and standard banking regulations. This is a scare tactic with no legal basis."
            },
            {
                "severity": "high",
                "title": "7-day notice violates SARFAESI Act mandatory 60-day period",
                "excerpt": "within 7 (seven) days from the date of this notice",
                "explanation": "Under Section 13(2) of the SARFAESI Act 2002, banks must give a minimum 60-day notice before initiating recovery action. A 7-day demand does not comply with this mandatory requirement."
            },
            {
                "severity": "medium",
                "title": "Criminal proceedings threat for civil debt is misleading",
                "excerpt": "Criminal proceedings under Section 138 of the Negotiable Instruments Act",
                "explanation": "Section 138 applies to dishonoured cheques, not general loan defaults. If no cheque was issued, this threat does not apply and misrepresents the legal situation."
            }
        ],
        "your_rights": [
            "You have the right to receive a proper 60-day notice under SARFAESI Act before any action is taken",
            "You cannot be arrested for civil loan default — threatening arrest is illegal",
            "You have the right to request a complete account statement showing all charges",
            "You have the right to file a complaint with the Banking Ombudsman free of charge",
            "Recovery agents cannot visit before 7am or after 7pm"
        ],
        "action_plan": [
            {"day": "Day 1-2", "action": "Do not panic. This notice has legal defects. Request a complete account statement in writing from HDFC Bank."},
            {"day": "Day 2-3", "action": "Send a written response disputing the 7-day timeline and citing the mandatory 60-day SARFAESI notice requirement."},
            {"day": "Day 3-4", "action": "File a complaint with the Banking Ombudsman at bankingombudsman.rbi.org.in — it is free and effective."},
            {"day": "Day 4-5", "action": "Verify the outstanding amount — request a full breakdown of principal, interest, and all charges."},
            {"day": "Day 5-7", "action": "If you can negotiate a settlement, the bank may accept a lower amount. Get any settlement offer in writing before paying."}
        ],
        "lawyer_needed": False,
        "lawyer_assessment": "You can handle this yourself initially. The notice has clear legal defects. File a Banking Ombudsman complaint and respond in writing citing the SARFAESI 60-day requirement. If the bank escalates to a Debt Recovery Tribunal or files suit, consult a lawyer at that point.",
        "template_response": "I write with reference to your notice dated 01 June 2026 regarding loan account XXXX-XXXX-8821. I wish to bring to your attention that this notice demands payment within 7 days, which does not comply with the mandatory 60-day notice period required under Section 13(2) of the SARFAESI Act 2002. Furthermore, the threat of arrest for civil loan default is not legally enforceable and violates the RBI Fair Practices Code. I request a complete and certified statement of account, including all principal, interest, and applicable charges, before I can address this matter further. All further communication must be in writing. I reserve my right to approach the Banking Ombudsman if this matter is not resolved appropriately.",
        "governing_law": "SARFAESI Act 2002, RBI Fair Practices Code, Recovery of Debts and Bankruptcy Act 1993",
        "response_deadline_days": 60,
        "forum": "Banking Ombudsman",
        "forum_url": "https://bankingombudsman.rbi.org.in"
    }

    db.documents.delete_many({"session_id": "demo-session"})
    db.documents.insert_one({
        "session_id": "demo-session",
        "country_code": "IN",
        "doc_type": "debt_collection",
        "raw_text": demo_doc_text,
        "analysis": demo_analysis,
        "filename": "HDFC_Recovery_Notice.pdf",
        "created_at": datetime.utcnow(),
    })

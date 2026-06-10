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

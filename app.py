import os
import threading
from datetime import date
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()

from mongo_client import (
    get_subscriptions, get_subscription, add_subscription, delete_subscription,
    get_bills, get_bill, add_bill, delete_bill, add_bill_reading,
    get_warranties, get_warranty, add_warranty, delete_warranty,
    get_groceries, get_grocery, add_grocery_item, add_grocery_price, delete_grocery,
    get_alerts, save_alert, seed_demo,
)
from gemini_client import (
    explain_subscription, explain_bill_spike,
    explain_warranty, explain_grocery_trend,
)
from checker import check_all

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "aretesapiens-dev-key")

USER_ID = "demo"

threading.Thread(target=lambda: check_all(USER_ID), daemon=True).start()


# ── Page ───────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Subscriptions ──────────────────────────────────────────────────────────────

@app.route("/api/subscriptions", methods=["GET"])
def api_get_subs():
    return jsonify(get_subscriptions(USER_ID))


@app.route("/api/subscriptions", methods=["POST"])
def api_add_sub():
    d = request.json or {}
    required = ["name", "amount", "next_renewal"]
    if not all(d.get(k) for k in required):
        return jsonify({"error": "name, amount, next_renewal required"}), 400
    add_subscription(
        user_id=USER_ID,
        name=d["name"],
        category=d.get("category", "other"),
        amount=d["amount"],
        currency=d.get("currency", "INR"),
        billing_cycle=d.get("billing_cycle", "monthly"),
        next_renewal=d["next_renewal"],
        started_on=d.get("started_on", date.today().isoformat()),
        notes=d.get("notes", ""),
    )
    return jsonify({"status": "ok"})


@app.route("/api/subscriptions/<doc_id>", methods=["DELETE"])
def api_del_sub(doc_id):
    delete_subscription(doc_id)
    return jsonify({"status": "ok"})


@app.route("/api/subscriptions/<doc_id>/explain", methods=["POST"])
def api_explain_sub(doc_id):
    sub = get_subscription(doc_id)
    if not sub:
        return jsonify({"error": "not found"}), 404
    billing_cycle = sub.get("billing_cycle", "monthly")
    annual_total = sub["amount"] * 12 if billing_cycle == "monthly" else sub["amount"]
    text = explain_subscription(
        sub["name"], sub["amount"], sub.get("price_history", []), annual_total
    )
    return jsonify({"explanation": text})


# ── Bills ──────────────────────────────────────────────────────────────────────

@app.route("/api/bills", methods=["GET"])
def api_get_bills():
    return jsonify(get_bills(USER_ID))


@app.route("/api/bills", methods=["POST"])
def api_add_bill():
    d = request.json or {}
    if not d.get("name"):
        return jsonify({"error": "name required"}), 400
    history = d.get("history", [])
    add_bill(
        user_id=USER_ID,
        name=d["name"],
        category=d.get("category", "other"),
        history=history,
        currency=d.get("currency", "INR"),
        alert_threshold_pct=d.get("alert_threshold_pct", 20),
    )
    return jsonify({"status": "ok"})


@app.route("/api/bills/<doc_id>", methods=["DELETE"])
def api_del_bill(doc_id):
    delete_bill(doc_id)
    return jsonify({"status": "ok"})


@app.route("/api/bills/<doc_id>/reading", methods=["POST"])
def api_add_bill_reading(doc_id):
    d = request.json or {}
    if not d.get("month") or d.get("amount") is None:
        return jsonify({"error": "month and amount required"}), 400
    add_bill_reading(doc_id, d["month"], d["amount"])
    return jsonify({"status": "ok"})


@app.route("/api/bills/<doc_id>/explain", methods=["POST"])
def api_explain_bill(doc_id):
    bill = get_bill(doc_id)
    if not bill:
        return jsonify({"error": "not found"}), 404
    history = bill.get("history", [])
    if len(history) < 2:
        return jsonify({"explanation": "Not enough history to analyze yet."})
    recent = history[-4:-1]
    avg = sum(h["amount"] for h in recent) / len(recent) if recent else 0
    latest = history[-1]["amount"]
    spike_pct = (latest - avg) / avg * 100 if avg else 0
    text = explain_bill_spike(bill["name"], history, spike_pct)
    return jsonify({"explanation": text})


# ── Warranties ─────────────────────────────────────────────────────────────────

@app.route("/api/warranties", methods=["GET"])
def api_get_warranties():
    return jsonify(get_warranties(USER_ID))


@app.route("/api/warranties", methods=["POST"])
def api_add_warranty():
    d = request.json or {}
    required = ["item_name", "purchase_date", "warranty_expiry", "purchase_price"]
    if not all(d.get(k) for k in required):
        return jsonify({"error": "item_name, purchase_date, warranty_expiry, purchase_price required"}), 400
    add_warranty(
        user_id=USER_ID,
        item_name=d["item_name"],
        category=d.get("category", "other"),
        purchase_date=d["purchase_date"],
        warranty_expiry=d["warranty_expiry"],
        purchase_price=d["purchase_price"],
        currency=d.get("currency", "INR"),
        notes=d.get("notes", ""),
    )
    return jsonify({"status": "ok"})


@app.route("/api/warranties/<doc_id>", methods=["DELETE"])
def api_del_warranty(doc_id):
    delete_warranty(doc_id)
    return jsonify({"status": "ok"})


@app.route("/api/warranties/<doc_id>/explain", methods=["POST"])
def api_explain_warranty(doc_id):
    w = get_warranty(doc_id)
    if not w:
        return jsonify({"error": "not found"}), 404
    try:
        expiry = date.fromisoformat(w["warranty_expiry"])
        days_until = (expiry - date.today()).days
    except Exception:
        days_until = 0
    text = explain_warranty(w["item_name"], days_until, w.get("purchase_price", 0))
    return jsonify({"explanation": text})


# ── Groceries ──────────────────────────────────────────────────────────────────

@app.route("/api/groceries", methods=["GET"])
def api_get_groceries():
    return jsonify(get_groceries(USER_ID))


@app.route("/api/groceries", methods=["POST"])
def api_add_grocery():
    d = request.json or {}
    if not d.get("item_name"):
        return jsonify({"error": "item_name required"}), 400
    from datetime import datetime
    initial_price = d.get("price", 0)
    prices = [{"date": datetime.utcnow().strftime("%Y-%m-%d"), "price": float(initial_price)}]
    add_grocery_item(
        user_id=USER_ID,
        item_name=d["item_name"],
        unit=d.get("unit", "pack"),
        price_history=prices,
        currency=d.get("currency", "INR"),
        usual_store=d.get("usual_store", ""),
    )
    return jsonify({"status": "ok"})


@app.route("/api/groceries/<doc_id>", methods=["DELETE"])
def api_del_grocery(doc_id):
    delete_grocery(doc_id)
    return jsonify({"status": "ok"})


@app.route("/api/groceries/<doc_id>/price", methods=["POST"])
def api_add_grocery_price(doc_id):
    d = request.json or {}
    if d.get("price") is None:
        return jsonify({"error": "price required"}), 400
    from datetime import datetime
    date_str = d.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    add_grocery_price(doc_id, date_str, d["price"])
    return jsonify({"status": "ok"})


@app.route("/api/groceries/<doc_id>/explain", methods=["POST"])
def api_explain_grocery(doc_id):
    item = get_grocery(doc_id)
    if not item:
        return jsonify({"error": "not found"}), 404
    text = explain_grocery_trend(item["item_name"], item.get("price_history", []))
    return jsonify({"explanation": text})


# ── Core ───────────────────────────────────────────────────────────────────────

@app.route("/api/alerts")
def api_get_alerts():
    return jsonify(get_alerts(USER_ID, limit=30))


@app.route("/api/run-checks", methods=["POST"])
def api_run_checks():
    threading.Thread(target=lambda: check_all(USER_ID), daemon=True).start()
    return jsonify({"status": "running"})


@app.route("/api/risk-score")
def api_risk_score():
    today = date.today()

    bills = get_bills(USER_ID)
    subs = get_subscriptions(USER_ID)
    warranties = get_warranties(USER_ID)
    groceries = get_groceries(USER_ID)

    score = 100
    factors = {
        "bills":         {"deductions": 0, "detail": ""},
        "subscriptions": {"deductions": 0, "detail": ""},
        "warranties":    {"deductions": 0, "detail": ""},
        "groceries":     {"deductions": 0, "detail": ""},
    }

    bill_anomalies = 0
    for bill in bills:
        history = bill.get("history", [])
        if len(history) < 2:
            continue
        recent = history[-4:-1]
        if not recent:
            continue
        avg = sum(h["amount"] for h in recent) / len(recent)
        latest = history[-1]["amount"]
        if avg > 0 and (latest - avg) / avg * 100 >= bill.get("alert_threshold_pct", 20):
            score -= 10
            bill_anomalies += 1
    factors["bills"]["deductions"] = bill_anomalies * 10
    factors["bills"]["detail"] = (
        f"{bill_anomalies} spike{'s' if bill_anomalies != 1 else ''}" if bill_anomalies else "All normal"
    )

    renewals_soon = 0
    for sub in subs:
        try:
            renewal = date.fromisoformat(sub["next_renewal"])
            if 0 <= (renewal - today).days <= 7:
                score -= 5
                renewals_soon += 1
        except Exception:
            pass
    factors["subscriptions"]["deductions"] = renewals_soon * 5
    factors["subscriptions"]["detail"] = (
        f"{renewals_soon} renewing soon" if renewals_soon else "All clear"
    )

    expiring_soon = 0
    for w in warranties:
        try:
            expiry = date.fromisoformat(w["warranty_expiry"])
            days = (expiry - today).days
            if 0 <= days <= 30:
                score -= 8
                expiring_soon += 1
        except Exception:
            pass
    factors["warranties"]["deductions"] = expiring_soon * 8
    factors["warranties"]["detail"] = (
        f"{expiring_soon} expiring soon" if expiring_soon else "All covered"
    )

    grocery_rising = 0
    for item in groceries:
        prices = item.get("price_history", [])
        if len(prices) >= 2:
            last_few = prices[-4:]
            if len(last_few) >= 2:
                old = last_few[0]["price"]
                new = last_few[-1]["price"]
                if old > 0 and (new - old) / old * 100 >= 15:
                    score -= 4
                    grocery_rising += 1
    factors["groceries"]["deductions"] = grocery_rising * 4
    factors["groceries"]["detail"] = (
        f"{grocery_rising} item{'s' if grocery_rising != 1 else ''} rising" if grocery_rising else "Prices stable"
    )

    score = max(0, min(100, score))
    level = "GOOD" if score >= 80 else "NEEDS ATTENTION" if score >= 50 else "AT RISK"

    return jsonify({"score": score, "level": level, "factors": factors})


@app.route("/api/seed-demo", methods=["POST"])
def api_seed_demo():
    seed_demo(USER_ID)
    threading.Thread(target=lambda: check_all(USER_ID), daemon=True).start()
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

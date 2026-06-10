import os
import uuid
import base64
import threading
from datetime import date, datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()

from mongo_client import (
    get_subscriptions, get_subscription, add_subscription, delete_subscription,
    get_bills, get_bill, add_bill, delete_bill, add_bill_reading,
    get_warranties, get_warranty, add_warranty, delete_warranty,
    get_groceries, get_grocery, add_grocery_item, add_grocery_price, delete_grocery,
    get_alerts, save_alert, seed_demo,
    is_premium, activate_trial,
    save_document, get_document, get_session_document,
    save_chat_message, get_chat_history,
    get_jurisdiction,
)
from gemini_client import (
    explain_subscription, explain_bill_spike,
    explain_warranty, explain_grocery_trend,
    detect_jurisdiction_fast, analyze_document, answer_followup,
)
from checker import check_all
from jurisdiction_loader import load_jurisdictions

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "aretesapiens-dev-key")

PRE_SEEDED_ANALYSIS = {
    "country_code": "IN",
    "country_name": "India",
    "document_type": "debt_collection",
    "confidence": 0.95,
    "signals_found": ["₹ symbol", "SARFAESI reference", "Banking Ombudsman mention"],
    "issuing_authority": "HDFC Bank Recovery Department",
    "analysis": {
        "summary": "This is a loan recovery notice from HDFC Bank demanding repayment of ₹2,40,000. The bank is threatening criminal proceedings and physical arrest if payment is not made within 7 days.",
        "severity": "medium",
        "rights": [
            "You have the right to receive a 60-day notice under SARFAESI before the bank can take any action on secured assets",
            "Recovery agents cannot visit your home before 7am or after 7pm under RBI guidelines",
            "You have the right to approach the Banking Ombudsman for free grievance redressal",
            "You can request a complete account statement showing all principal, interest, and charges"
        ],
        "enforceability_issues": [
            "The letter states 'legal action will be initiated within 7 days' — SARFAESI Act requires a mandatory 60-day notice period. This 7-day threat is premature and legally incorrect.",
            "The letter threatens 'criminal proceedings' and 'FIR' for loan default — civil debt default cannot result in arrest. This violates the RBI Fair Practices Code for Lenders (2003 circular).",
            "The letter states agents will visit 'at any hour of the day or night' — RBI guidelines strictly prohibit recovery agent visits outside 7am–7pm."
        ],
        "action_items": [
            {"days_from_now": 1, "action": "Send a written dispute letter to HDFC Bank requesting full account statement", "why": "Creates a paper trail and triggers their legal obligation to respond formally", "urgent": True},
            {"days_from_now": 3, "action": "File a complaint with the Banking Ombudsman if the bank does not acknowledge your dispute", "why": "Free, fast, and effective — banks take RBI Ombudsman complaints very seriously", "urgent": False},
            {"days_from_now": 7, "action": "Send final written response using the template letter below before this deadline", "why": "Silence on a legal notice can be interpreted as admission in court", "urgent": True}
        ],
        "lawyer_needed": False,
        "lawyer_reason": "This is a standard recovery notice with multiple procedural violations. You can handle the initial response yourself using the template below. Only engage a lawyer if the bank proceeds to file in the Debt Recovery Tribunal (DRT).",
        "free_resources": [
            {"name": "Banking Ombudsman", "url": "https://bankingombudsman.rbi.org.in", "description": "Free RBI grievance redressal — file online in 10 minutes"},
            {"name": "RBI Sachet Portal", "url": "https://sachet.rbi.org.in", "description": "Report illegal recovery practices to the RBI directly"}
        ],
        "template_response": "I write with reference to your notice dated [DATE] regarding loan account [NUMBER]. I wish to bring to your attention that this notice does not comply with the mandatory 60-day period required under the SARFAESI Act 2002. I also note that threatening criminal consequences for civil loan default violates the RBI Fair Practices Code for Lenders. I request a complete statement of account including all principal, interest, and charges. All further communication must be in writing to the address above. I reserve my right to approach the Banking Ombudsman if this matter is not resolved appropriately."
    }
}

USER_ID = "demo"

# Seed jurisdictions and run initial checks in background (avoids blocking gunicorn startup)
def _startup():
    try:
        load_jurisdictions()
    except Exception as e:
        print(f"[startup] jurisdiction load error: {e}")
    try:
        seed_demo(USER_ID)
    except Exception as e:
        print(f"[startup] seed_demo error: {e}")
    try:
        check_all(USER_ID)
    except Exception as e:
        print(f"[startup] check_all error: {e}")

threading.Thread(target=_startup, daemon=True).start()


# ── Page ───────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Premium Gate ───────────────────────────────────────────────────────────────

@app.route("/api/premium-status")
def api_premium_status():
    return jsonify({"is_premium": is_premium(USER_ID)})


@app.route("/api/activate-trial", methods=["POST"])
def api_activate_trial():
    activate_trial(USER_ID)
    return jsonify({"status": "ok", "is_premium": True})


def require_premium():
    if not is_premium(USER_ID):
        return jsonify({"error": "premium_required", "message": "Financial Health requires a premium subscription."}), 403
    return None


# ── Vaakil: Demo ──────────────────────────────────────────────────────────────

@app.route("/api/vaakil/demo")
def api_vaakil_demo():
    return jsonify(PRE_SEEDED_ANALYSIS)


# ── Vaakil: Document Analysis ─────────────────────────────────────────────────

@app.route("/api/vaakil/analyze", methods=["POST"])
def api_vaakil_analyze():
    session_id = request.form.get("session_id") or str(uuid.uuid4())
    doc_text = request.form.get("text", "").strip()
    hint_country = request.form.get("country", "").strip().upper() or None
    filename = None
    image_b64 = None
    image_mime = None

    # Handle file upload
    if "file" in request.files:
        f = request.files["file"]
        filename = f.filename
        mime = f.content_type or ""
        try:
            raw = f.read()
            if mime.startswith("image/") or filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                # Pass image directly to Gemini Vision
                image_b64 = base64.b64encode(raw).decode("utf-8")
                image_mime = mime if mime.startswith("image/") else "image/jpeg"
            elif mime == "application/pdf" or filename.lower().endswith(".pdf"):
                # Pass PDF bytes to Gemini as inline data
                image_b64 = base64.b64encode(raw).decode("utf-8")
                image_mime = "application/pdf"
            else:
                try:
                    doc_text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    doc_text = raw.decode("latin-1", errors="replace")
        except Exception as e:
            return jsonify({"error": f"Could not read file: {str(e)}"}), 400

    if not doc_text and not image_b64:
        return jsonify({"error": "No document text or file provided"}), 400

    # Step 1: Fast keyword-based detection (instant — no API call)
    if image_b64 and not doc_text:
        # For pure image uploads: use hint country or default to India
        country_code = hint_country or "IN"
        country_name_map = {"IN": "India", "US": "United States", "GB": "United Kingdom", "AU": "Australia", "CA": "Canada", "NG": "Nigeria"}
        country_name = country_name_map.get(country_code, "India")
        doc_type = "other"
    else:
        country_code, country_name, doc_type = detect_jurisdiction_fast(doc_text)
        if hint_country and hint_country in ("IN", "US", "GB", "AU", "CA", "NG"):
            country_code = hint_country
            country_name_map = {"IN": "India", "US": "United States", "GB": "United Kingdom", "AU": "Australia", "CA": "Canada", "NG": "Nigeria"}
            country_name = country_name_map.get(country_code, country_name)

    # Step 2: Fetch jurisdiction ruleset from MongoDB
    jurisdiction_data = get_jurisdiction(country_code)
    if not jurisdiction_data:
        jurisdiction_data = get_jurisdiction("IN") or {}

    # Step 3: Analyze with Gemini (text or image)
    analysis = analyze_document(doc_text, jurisdiction_data, doc_type, image_b64=image_b64, image_mime=image_mime)

    # Step 4: Save to MongoDB
    doc_id = save_document(session_id, country_code, doc_type, doc_text or f"[Image: {filename}]", analysis, filename)

    return jsonify({
        "session_id": session_id,
        "doc_id": doc_id,
        "country_code": country_code,
        "country_name": country_name,
        "document_type": doc_type,
        "confidence": 0.92 if not image_b64 else 0.85,
        "signals_found": [],
        "issuing_authority": analysis.get("issuing_authority", "Unknown"),
        "analysis": analysis,
    })


@app.route("/api/vaakil/document/<session_id>")
def api_vaakil_get_document(session_id):
    doc = get_session_document(session_id)
    if not doc:
        return jsonify({"error": "not found"}), 404
    return jsonify(doc)


@app.route("/api/vaakil/chat", methods=["POST"])
def api_vaakil_chat():
    d = request.json or {}
    session_id = d.get("session_id")
    question = d.get("question", "").strip()

    if not session_id or not question:
        return jsonify({"error": "session_id and question required"}), 400

    doc = get_session_document(session_id)
    if not doc:
        return jsonify({"error": "No document found for this session"}), 404

    analysis = doc.get("analysis", {})
    doc_summary = analysis.get("summary") or analysis.get("plain_summary", "A legal document")
    country_name = analysis.get("country") or analysis.get("country_name", "your country")

    # Save user message
    save_chat_message(session_id, "user", question)

    # Get history
    history = get_chat_history(session_id)

    # Get Gemini answer — pass full analysis context
    answer = answer_followup(question, doc_summary, history[:-1], country_name, full_analysis=analysis)

    # Save assistant response
    save_chat_message(session_id, "assistant", answer)

    return jsonify({"answer": answer})


# ── Subscriptions ──────────────────────────────────────────────────────────────

@app.route("/api/subscriptions", methods=["GET"])
def api_get_subs():
    gate = require_premium()
    if gate:
        return gate
    return jsonify(get_subscriptions(USER_ID))


@app.route("/api/subscriptions", methods=["POST"])
def api_add_sub():
    gate = require_premium()
    if gate:
        return gate
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
    gate = require_premium()
    if gate:
        return gate
    delete_subscription(doc_id)
    return jsonify({"status": "ok"})


@app.route("/api/subscriptions/<doc_id>/explain", methods=["POST"])
def api_explain_sub(doc_id):
    gate = require_premium()
    if gate:
        return gate
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
    gate = require_premium()
    if gate:
        return gate
    return jsonify(get_bills(USER_ID))


@app.route("/api/bills", methods=["POST"])
def api_add_bill():
    gate = require_premium()
    if gate:
        return gate
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
    gate = require_premium()
    if gate:
        return gate
    delete_bill(doc_id)
    return jsonify({"status": "ok"})


@app.route("/api/bills/<doc_id>/reading", methods=["POST"])
def api_add_bill_reading(doc_id):
    gate = require_premium()
    if gate:
        return gate
    d = request.json or {}
    if not d.get("month") or d.get("amount") is None:
        return jsonify({"error": "month and amount required"}), 400
    add_bill_reading(doc_id, d["month"], d["amount"])
    return jsonify({"status": "ok"})


@app.route("/api/bills/<doc_id>/explain", methods=["POST"])
def api_explain_bill(doc_id):
    gate = require_premium()
    if gate:
        return gate
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
    gate = require_premium()
    if gate:
        return gate
    return jsonify(get_warranties(USER_ID))


@app.route("/api/warranties", methods=["POST"])
def api_add_warranty():
    gate = require_premium()
    if gate:
        return gate
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
    gate = require_premium()
    if gate:
        return gate
    delete_warranty(doc_id)
    return jsonify({"status": "ok"})


@app.route("/api/warranties/<doc_id>/explain", methods=["POST"])
def api_explain_warranty(doc_id):
    gate = require_premium()
    if gate:
        return gate
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
    gate = require_premium()
    if gate:
        return gate
    return jsonify(get_groceries(USER_ID))


@app.route("/api/groceries", methods=["POST"])
def api_add_grocery():
    gate = require_premium()
    if gate:
        return gate
    d = request.json or {}
    if not d.get("item_name"):
        return jsonify({"error": "item_name required"}), 400
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
    gate = require_premium()
    if gate:
        return gate
    delete_grocery(doc_id)
    return jsonify({"status": "ok"})


@app.route("/api/groceries/<doc_id>/price", methods=["POST"])
def api_add_grocery_price(doc_id):
    gate = require_premium()
    if gate:
        return gate
    d = request.json or {}
    if d.get("price") is None:
        return jsonify({"error": "price required"}), 400
    date_str = d.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    add_grocery_price(doc_id, date_str, d["price"])
    return jsonify({"status": "ok"})


@app.route("/api/groceries/<doc_id>/explain", methods=["POST"])
def api_explain_grocery(doc_id):
    gate = require_premium()
    if gate:
        return gate
    item = get_grocery(doc_id)
    if not item:
        return jsonify({"error": "not found"}), 404
    text = explain_grocery_trend(item["item_name"], item.get("price_history", []))
    return jsonify({"explanation": text})


# ── Core (premium-gated) ───────────────────────────────────────────────────────

@app.route("/api/alerts")
def api_get_alerts():
    gate = require_premium()
    if gate:
        return gate
    return jsonify(get_alerts(USER_ID, limit=30))


@app.route("/api/run-checks", methods=["POST"])
def api_run_checks():
    gate = require_premium()
    if gate:
        return gate
    threading.Thread(target=lambda: check_all(USER_ID), daemon=True).start()
    return jsonify({"status": "running"})


@app.route("/api/risk-score")
def api_risk_score():
    gate = require_premium()
    if gate:
        return gate
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

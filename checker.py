from datetime import date, timedelta
from mongo_client import (
    get_bills, get_subscriptions, get_warranties, get_groceries,
    save_alert, alert_exists_for_source,
)
from gemini_client import (
    explain_bill_spike, explain_subscription,
    explain_warranty, explain_grocery_trend,
)

USER_ID = "demo"


def check_all(user_id=USER_ID):
    check_bills(user_id)
    check_subscriptions(user_id)
    check_warranties(user_id)
    check_groceries(user_id)


def check_bills(user_id=USER_ID):
    for bill in get_bills(user_id):
        history = bill.get("history", [])
        if len(history) < 2:
            continue

        threshold = float(bill.get("alert_threshold_pct", 20))
        recent_avg_window = history[-4:-1]
        if not recent_avg_window:
            continue

        avg = sum(h["amount"] for h in recent_avg_window) / len(recent_avg_window)
        latest_amount = history[-1]["amount"]

        if avg == 0:
            continue

        spike_pct = (latest_amount - avg) / avg * 100
        if spike_pct < threshold:
            continue

        source_id = bill["id"]
        if alert_exists_for_source(source_id, "bills"):
            continue

        body = explain_bill_spike(bill["name"], history, spike_pct)
        severity = "high" if spike_pct >= 40 else "medium"
        save_alert(
            user_id=user_id,
            module="bills",
            title=f"{bill['name']} spiked {spike_pct:.0f}% above average",
            body=body,
            severity=severity,
            source_id=source_id,
        )


def check_subscriptions(user_id=USER_ID):
    today = date.today()

    for sub in get_subscriptions(user_id):
        source_id = sub["id"]

        # Renewal within 7 days
        try:
            renewal = date.fromisoformat(sub["next_renewal"])
            days_until = (renewal - today).days
            if 0 <= days_until <= 7:
                if not alert_exists_for_source(source_id, "subscriptions"):
                    billing_cycle = sub.get("billing_cycle", "monthly")
                    annual_total = sub["amount"] * 12 if billing_cycle == "monthly" else sub["amount"]
                    body = explain_subscription(
                        sub["name"], sub["amount"],
                        sub.get("price_history", []), annual_total,
                    )
                    severity = "high" if days_until <= 2 else "medium"
                    save_alert(
                        user_id=user_id,
                        module="subscriptions",
                        title=f"{sub['name']} renews in {days_until} day{'s' if days_until != 1 else ''}",
                        body=body,
                        severity=severity,
                        source_id=source_id,
                    )
        except (ValueError, TypeError):
            pass

        # Price increase in history
        ph = sub.get("price_history", [])
        if len(ph) >= 2:
            old_price = ph[-2]["amount"]
            new_price = ph[-1]["amount"]
            if new_price > old_price:
                hike_key = f"{source_id}:price_hike"
                if not alert_exists_for_source(hike_key, "subscriptions", hours=720):
                    increase_pct = (new_price - old_price) / old_price * 100
                    billing_cycle = sub.get("billing_cycle", "monthly")
                    annual_total = sub["amount"] * 12 if billing_cycle == "monthly" else sub["amount"]
                    body = explain_subscription(sub["name"], sub["amount"], ph, annual_total)
                    save_alert(
                        user_id=user_id,
                        module="subscriptions",
                        title=f"{sub['name']} price hiked {increase_pct:.0f}% (₹{old_price:.0f} → ₹{new_price:.0f})",
                        body=body,
                        severity="medium",
                        source_id=hike_key,
                    )


def check_warranties(user_id=USER_ID):
    today = date.today()

    for w in get_warranties(user_id):
        source_id = w["id"]
        try:
            expiry = date.fromisoformat(w["warranty_expiry"])
            days_until = (expiry - today).days
        except (ValueError, TypeError):
            continue

        if days_until < 0:
            continue

        if days_until <= 30:
            if alert_exists_for_source(source_id, "warranties"):
                continue
            body = explain_warranty(w["item_name"], days_until, w.get("purchase_price", 0))
            severity = "high" if days_until <= 14 else "medium"
            save_alert(
                user_id=user_id,
                module="warranties",
                title=f"{w['item_name']} warranty expires in {days_until} days",
                body=body,
                severity=severity,
                source_id=source_id,
            )


def check_groceries(user_id=USER_ID):
    for item in get_groceries(user_id):
        prices = item.get("price_history", [])
        if len(prices) < 2:
            continue

        prev_price = prices[-2]["price"]
        curr_price = prices[-1]["price"]

        if prev_price == 0:
            continue

        change_pct = (curr_price - prev_price) / prev_price * 100
        if change_pct < 10:
            continue

        source_id = item["id"]
        if alert_exists_for_source(source_id, "groceries"):
            continue

        body = explain_grocery_trend(item["item_name"], prices)
        severity = "high" if change_pct >= 20 else "medium"
        save_alert(
            user_id=user_id,
            module="groceries",
            title=f"{item['item_name']} up {change_pct:.0f}% since last reading",
            body=body,
            severity=severity,
            source_id=source_id,
        )

import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = "gemini-2.0-flash"
_CONFIG = types.GenerateContentConfig(temperature=0.3)


def _generate(prompt):
    try:
        response = _client.models.generate_content(
            model=MODEL, contents=prompt, config=_CONFIG
        )
        return response.text.strip()
    except Exception as e:
        print(f"[gemini] error: {e}")
        return None


def explain_bill_spike(bill_name, history, spike_pct):
    history_text = ", ".join(f"{h['month']}: ₹{h['amount']}" for h in history[-6:])
    prompt = (
        f"You are a household finance assistant. A user's {bill_name} bill spiked "
        f"{spike_pct:.1f}% this month compared to their 6-month average.\n\n"
        f"Bill history: {history_text}\n\n"
        f"Explain in 2-3 plain English sentences what likely caused this and what they "
        f"should check. Be specific, not generic."
    )
    result = _generate(prompt)
    return result or (
        f"Your {bill_name} bill has risen {spike_pct:.0f}% above your recent average. "
        f"Check for increased usage, rate changes from your provider, or any one-time charges "
        f"that may have been added this billing cycle."
    )


def explain_subscription(name, amount, price_history, annual_total):
    history_text = ", ".join(f"₹{p['amount']} from {p['from']}" for p in price_history)
    prompt = (
        f"A user pays ₹{amount}/month for {name}. "
        f"They have paid ₹{annual_total:.0f} on this subscription in the past 12 months.\n\n"
        f"Price history: {history_text}\n\n"
        f"In 2-3 sentences: is this good value? Has the price crept up? "
        f"What should they consider? Be specific with rupee amounts."
    )
    result = _generate(prompt)
    return result or (
        f"You're paying ₹{amount}/month for {name}, which totals ₹{annual_total:.0f} annually. "
        f"Review your usage frequency — if you're not actively using this service every week, "
        f"cancelling would free up meaningful budget."
    )


def explain_warranty(item_name, days_until_expiry, purchase_price):
    if days_until_expiry < 0:
        timing = f"expired {abs(days_until_expiry)} days ago"
    else:
        timing = f"expires in {days_until_expiry} days"
    prompt = (
        f"A user's warranty for {item_name} (purchased for ₹{purchase_price:,.0f}) {timing}.\n\n"
        f"In 2-3 sentences: what are the risks of no warranty coverage, what should they do now, "
        f"and roughly what would a replacement or out-of-warranty repair cost in India? "
        f"Be specific with rupee estimates."
    )
    result = _generate(prompt)
    return result or (
        f"Without warranty coverage, any repair for your {item_name} will be fully out-of-pocket. "
        f"Major repairs on this category of device in India typically cost ₹8,000–₹35,000 depending "
        f"on the issue. Consider purchasing an extended warranty or setting aside a repair fund now."
    )


def explain_grocery_trend(item_name, price_history):
    history_text = ", ".join(
        f"{p['date'][:7]}: ₹{p['price']}" for p in price_history[-6:]
    )
    prompt = (
        f"A user tracks the price of {item_name}. "
        f"Price history over the last 6 months: {history_text}.\n\n"
        f"In 2 sentences, describe the price trend and whether this matches broader "
        f"food inflation patterns in India."
    )
    result = _generate(prompt)
    return result or (
        f"The price of {item_name} has been trending upward over recent months, "
        f"consistent with broader food inflation in India. "
        f"Buying in bulk when prices dip or switching to store-brand alternatives can help offset the increase."
    )

import os
import json
import concurrent.futures
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = "gemini-2.0-flash"
_CONFIG = types.GenerateContentConfig(temperature=0.3)
_CONFIG_STRICT = types.GenerateContentConfig(temperature=0.0)
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _generate(prompt, strict=False, timeout=22):
    try:
        cfg = _CONFIG_STRICT if strict else _CONFIG
        future = _EXECUTOR.submit(
            _client.models.generate_content,
            model=MODEL, contents=prompt, config=cfg
        )
        response = future.result(timeout=timeout)
        return response.text.strip()
    except concurrent.futures.TimeoutError:
        print(f"[gemini] timed out after {timeout}s")
        return None
    except Exception as e:
        print(f"[gemini] error: {e}")
        return None


def _parse_json(text):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    try:
        return json.loads(text)
    except Exception:
        return None


# ── Vaakil: Fast keyword-based detection (no API call) ────────────────────────

def detect_jurisdiction_fast(doc_text):
    """Instant country + doc-type detection via keyword matching. No Gemini call."""
    text = doc_text[:3000].lower()

    # Country detection — most specific signals first
    if any(x in text for x in ['₹', 'inr', 'sarfaesi', ' rbi ', 'sebi ', 'hdfc', 'icici', 'bescom',
                                 'nbfc', 'ncdrc', 'rupee', 'lakh', 'crore', 'india', 'indian']):
        country_code, country_name = 'IN', 'India'
    elif any(x in text for x in ['₦', 'ngn', 'naira', 'cbn ', 'efcc', 'fccpc', 'nigeria', 'nigerian']):
        country_code, country_name = 'NG', 'Nigeria'
    elif any(x in text for x in ['£', 'gbp', 'hmrc', 'fca ', 'acas ', 'county court', 'ofgem',
                                   'england', 'wales', 'scotland', 'uk ', 'united kingdom']):
        country_code, country_name = 'GB', 'United Kingdom'
    elif any(x in text for x in ['a$', 'aud', 'vcat', 'ncat', 'qcat', 'afca', 'accc', 'centrelink',
                                   'fair work', 'australia', 'australian']):
        country_code, country_name = 'AU', 'Australia'
    elif any(x in text for x in ['c$', 'cad', 'cra ', ' ltb ', ' rtb ', 'canada', 'canadian',
                                   'ontario', 'british columbia', 'alberta']):
        country_code, country_name = 'CA', 'Canada'
    elif any(x in text for x in ['fdcpa', 'cfpb', 'eeoc', ' irs ', 'osha ', 'usd', 'united states',
                                   'american', 'federal court', 'bankruptcy court']):
        country_code, country_name = 'US', 'United States'
    elif '$' in text:
        country_code, country_name = 'US', 'United States'
    else:
        country_code, country_name = 'IN', 'India'

    # Doc type detection
    if any(x in text for x in ['debt', 'loan', 'recovery', 'outstanding', 'overdue', 'collection',
                                 'arrears', 'repayment', 'default notice', 'demand notice']):
        doc_type = 'debt_collection'
    elif any(x in text for x in ['evict', 'vacate', 'quit notice', 'tenancy', 'terminate your tenancy',
                                   'leave the premises', 'notice to quit', 'possession']):
        doc_type = 'eviction_notice'
    elif any(x in text for x in ['summons', 'writ', 'lawsuit', 'filed a claim', 'statement of claim',
                                   'plaintiff', 'defendant', 'court order']):
        doc_type = 'court_summons'
    elif any(x in text for x in ['terminat', 'dismiss', 'retrench', 'layoff', 'redundan',
                                   'employment end', 'last working day', 'separation']):
        doc_type = 'employment_termination'
    elif any(x in text for x in ['consumer', 'refund', 'defective', 'warranty claim',
                                   'not fit for purpose', 'misleading']):
        doc_type = 'consumer_notice'
    else:
        doc_type = 'other'

    return country_code, country_name, doc_type


# ── Vaakil: Jurisdiction Detection (Gemini fallback — kept for reference) ─────

def detect_jurisdiction(doc_text):
    """Returns {"country_code": "IN", "country_name": "India", "doc_type": "debt_collection", "confidence": 0.95}"""
    prompt = f"""You are a legal document classifier. Analyze the following document text and identify:
1. The country it is from (based on currency symbols, court names, regulatory bodies, legal citations, or any country-specific references)
2. The document type

Return ONLY a JSON object with these exact fields:
{{
  "country_code": "two-letter ISO code e.g. IN, US, GB, AU, CA, NG",
  "country_name": "full country name",
  "doc_type": "one of: debt_collection, eviction_notice, court_summons, employment_termination, consumer_notice, other",
  "doc_type_label": "human-readable label e.g. Debt Recovery Notice",
  "confidence": 0.0 to 1.0,
  "detection_clues": ["list of text clues that helped identify country and type"]
}}

Document text:
---
{doc_text[:3000]}
---

Return only the JSON, no markdown, no explanation."""

    result = _generate(prompt, strict=True)
    parsed = _parse_json(result)
    if parsed and "country_code" in parsed:
        return parsed
    return {
        "country_code": "IN",
        "country_name": "India",
        "doc_type": "other",
        "doc_type_label": "Legal Document",
        "confidence": 0.3,
        "detection_clues": []
    }


# ── Vaakil: Document Analysis ─────────────────────────────────────────────────

def analyze_document(doc_text, jurisdiction_data, doc_type):
    """Full legal analysis using jurisdiction ruleset from MongoDB."""
    doc_type_info = jurisdiction_data.get("document_types", {}).get(doc_type, {})

    rights_list = "\n".join(f"- {r}" for r in doc_type_info.get("key_rights", []))
    violations_list = "\n".join(f"- {v}" for v in doc_type_info.get("common_violations", []))
    governing_law = doc_type_info.get("governing_law", "Applicable national law")
    forum = doc_type_info.get("forum", "Relevant court or authority")
    forum_url = doc_type_info.get("forum_url", "")
    template = doc_type_info.get("template_response", "")
    country_name = jurisdiction_data.get("country_name", "Unknown")

    prompt = f"""You are Vaakil, an empathetic legal aid assistant for {country_name}. Analyze this {doc_type.replace('_', ' ')} document.

Governing law: {governing_law}
Rights the user has:
{rights_list}
Violations to check for:
{violations_list}

DOCUMENT:
{doc_text[:2500]}

Return ONLY this JSON (no markdown, no code fences):
{{"summary":"2-3 plain-language sentences explaining what this document demands","severity":"low|medium|high","rights":["right1","right2","right3","right4"],"enforceability_issues":["Specific illegal threat or violation found — quote exact text from document. Empty list if none found."],"action_items":[{{"days_from_now":1,"action":"specific step to take","why":"why this is critical","urgent":true}},{{"days_from_now":3,"action":"next step","why":"reason","urgent":false}},{{"days_from_now":7,"action":"final step","why":"reason","urgent":false}}],"lawyer_needed":false,"lawyer_reason":"clear explanation of whether user needs a lawyer or can self-handle with template","free_resources":[{{"name":"Resource name","url":"https://...","description":"brief description"}}],"template_response":"Full professional response letter the user can send"}}

Quote real text from the document for enforceability_issues. Return valid JSON only."""

    result = _generate(prompt, strict=True)
    parsed = _parse_json(result)

    if parsed:
        return parsed

    return _offline_fallback(doc_type_info, governing_law, forum, forum_url, template, country_name, doc_type)


def _offline_fallback(rule, governing_law, forum, forum_url, template, country_name, doc_type):
    """Rich offline fallback using jurisdiction data when Gemini times out."""
    severity = "high" if doc_type in ("court_summons", "eviction_notice") else "medium"
    forum_resource = []
    if forum and forum_url:
        forum_resource = [{"name": forum, "url": forum_url, "description": f"Official filing portal for {country_name} citizens."}]
    response_window = rule.get("response_window_days", 30)
    return {
        "summary": f"[Offline Analysis] This appears to be a {doc_type.replace('_', ' ')} document subject to the {governing_law} of {country_name}. Review the rights and violations listed below carefully.",
        "severity": severity,
        "rights": rule.get("key_rights", ["You have the right to respond to this document in writing."]),
        "enforceability_issues": [f"{v} (Common statutory violation of {governing_law})" for v in rule.get("common_violations", [])],
        "action_items": [
            {"days_from_now": 1, "action": f"Review your rights under the {governing_law}", "why": "Crucial statute protecting you", "urgent": True},
            {"days_from_now": 3, "action": "Draft a formal written challenge citing your rights below", "why": "Stops automatic timelines from lapsing", "urgent": True},
            {"days_from_now": response_window, "action": "Final legal response window closes", "why": "Must respond before this deadline to avoid default", "urgent": False},
        ],
        "lawyer_needed": not rule.get("self_handleable", True),
        "lawyer_reason": f"Use the template response below to challenge this notice. Escalate to the {forum} only if the issuer does not respond within 30 days.",
        "free_resources": forum_resource,
        "template_response": template or f"I am writing with reference to your notice. I assert all my rights under the {governing_law} of {country_name}. Please communicate with me strictly in writing at the address above.",
    }


# ── Vaakil: Follow-up Q&A ─────────────────────────────────────────────────────

def answer_followup(question, doc_summary, chat_history, country_name):
    history_text = ""
    for msg in chat_history[-6:]:
        role = "User" if msg["role"] == "user" else "Assistant"
        history_text += f"{role}: {msg['content']}\n"

    prompt = f"""You are a legal assistant helping a user in {country_name} understand their legal document.

Document summary: {doc_summary}

Previous conversation:
{history_text}
User: {question}

Provide a helpful, accurate, plain-language answer. Be specific to {country_name} law. If you're unsure about a specific legal point, say so and recommend they verify with a qualified lawyer. Keep your response under 200 words and conversational."""

    result = _generate(prompt)
    return result or "I'm sorry, I couldn't process that question. Please try rephrasing it or consult a legal professional for specific advice."


# ── Financial Health: Gemini Explanations ─────────────────────────────────────

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

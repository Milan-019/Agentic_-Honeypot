"""
LangGraph Nodes for the Agentic Honeypot pipeline.

Each node receives the full HoneypotState, does ONE job, 
and returns a dict of fields to update.

Node order:
  intake_node → strategy_node → persona_node → extractor_node → guard_node
"""

import re
import uuid
import logging
from datetime import datetime

from core.state import (
    HoneypotState,
    ExtractedIntel,
    ScamType,
    ThreatLevel,
    EngagementStrategy,
    PersonaState,
)
from core.llm_client import llm

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 1 — INTAKE (Classify the scammer's message)
# ═══════════════════════════════════════════════════════════════════════════════

INTAKE_SYSTEM = """You are a cybersecurity AI specializing in Indian financial fraud (UPI scams, phishing, etc.).
Analyze the incoming message and classify it.

Respond ONLY with this JSON structure:
{
  "scam_type": "<upi_fraud|phishing|fake_lottery|job_scam|romance_scam|tech_support|unknown>",
  "threat_level": "<low|medium|high|critical>",
  "confidence_score": <0.0 to 1.0>,
  "scam_indicators": ["list", "of", "red", "flags", "found"]
}

Threat level guide:
- low: generic suspicious message, no clear ask yet
- medium: asking for personal info or showing money lure
- high: direct ask for money transfer / UPI payment
- critical: urgent pressure + money ask + specific amounts
"""


def intake_node(state: HoneypotState) -> dict:
    """Classify the scammer's message — scam type, threat level, indicators."""
    message = state.current_scammer_message
    if not message:
        return {}

    raw, model = llm.chat(INTAKE_SYSTEM, message, json_mode=True)
    data = llm.parse_json_response(raw)

    return {
        "scam_type": data.get("scam_type", "unknown"),
        "threat_level": data.get("threat_level", "low"),
        "confidence_score": float(data.get("confidence_score", 0.5)),
        "scam_indicators": data.get("scam_indicators", []),
        "model_used": model,
        "session_id": state.session_id or str(uuid.uuid4())[:8],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 2 — STRATEGY (Decide HOW to respond)
# ═══════════════════════════════════════════════════════════════════════════════

STRATEGY_SYSTEM = """You are a tactical AI deciding how an undercover honeypot agent should respond to a scammer.

Goals (in order):
1. WASTE the scammer's time as long as possible
2. EXTRACT intelligence: UPI IDs, bank names, phone numbers, account details
3. NEVER reveal you are a bot

Available strategies:
- play_dumb: Act confused, ask basic questions that delay the scammer
- stall: Give excuses (bad internet, can't find phone, need to ask family)
- request_info: Pretend to be ready to pay — ask for their payment details (UPI ID, bank account)
- escalate: Show growing eagerness, push them to confirm their receiving details
- terminate: End the conversation (scammer has gone cold or our intel is complete)

Current conversation context is provided. Choose the OPTIMAL strategy.

Respond ONLY with JSON:
{
  "strategy": "<play_dumb|stall|request_info|escalate|terminate>",
  "persona": "<naive_victim|cautiously_interested|eager_victim>",
  "reasoning": "brief explanation of why this strategy now"
}
"""


def strategy_node(state: HoneypotState) -> dict:
    """Decide the engagement strategy based on conversation state."""
    context = f"""
Scam Type: {state.scam_type}
Threat Level: {state.threat_level}
Turn Number: {state.turn_count}
Intel Collected So Far: UPI IDs={state.intel.upi_ids}, Phones={state.intel.phone_numbers}
Intel Yield Score: {state.intel_yield_score:.2f}

Last Scammer Message: {state.current_scammer_message}

Conversation History (last 6 turns):
{_format_recent_messages(state.messages, n=6)}
"""

    raw, _ = llm.chat(STRATEGY_SYSTEM, context, json_mode=True)
    data = llm.parse_json_response(raw)

    strategy = data.get("strategy", "play_dumb")
    # Force terminate if we've gone too long or have great intel
    if state.turn_count >= state.max_turns:
        strategy = "terminate"
    if state.intel_yield_score >= 0.9:
        strategy = "terminate"

    return {
        "engagement_strategy": strategy,
        "persona": data.get("persona", "naive_victim"),
        "strategy_reasoning": data.get("reasoning", ""),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 3 — PERSONA (Generate the actual response text)
# ═══════════════════════════════════════════════════════════════════════════════

PERSONA_SYSTEM = """You are roleplaying as a honeypot victim persona to trap a scammer.

PERSONA GUIDELINES:
- naive_victim: Elderly Indian person (60+), calls UPI "the app", limited digital literacy, 
  speaks broken Hindi-English mix, confused about technology, trusting
- cautiously_interested: Middle-aged first-time digital user, slightly hesitant, 
  asks clarifying questions, occasionally suspicious but can be persuaded
- eager_victim: Appears ready to transfer money but always needs "one more detail" 
  from the scammer before doing so (fishing for their UPI/bank info)

STRATEGY EXECUTION:
- play_dumb: Ask a genuinely confusing question about basic tech/UPI 
- stall: Give a plausible excuse for delay (e.g., "phone is with son", "net is slow", "will do tomorrow")
- request_info: Say you're ready to pay but need to confirm their UPI ID / account number first
- escalate: Express excitement, say you've told your family, ask them to confirm their receiving details
- terminate: Politely end (e.g., "I think I need to check with my bank first")

IMPORTANT:
- Keep responses SHORT (1-3 sentences max) — scammers get suspicious with long replies
- Stay in character — NEVER break persona
- Use natural informal language, occasional Hindi words (acha, theek hai, bhai, etc.) where natural
- DO NOT reveal any real personal information
"""


def persona_node(state: HoneypotState) -> dict:
    """Generate the in-character honeypot response."""
    user_prompt = f"""
Strategy to execute: {state.engagement_strategy}
Persona: {state.persona}
Scam type: {state.scam_type}

Scammer's message: {state.current_scammer_message}

Recent conversation:
{_format_recent_messages(state.messages, n=4)}

Generate your response as the victim persona. Keep it 1-3 sentences.
"""

    response_text, _ = llm.chat(PERSONA_SYSTEM, user_prompt, json_mode=False)

    return {
        "bot_response": response_text.strip(),
        "turn_count": state.turn_count + 1,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 4 — EXTRACTOR (Harvest intelligence from scammer's message)
# ═══════════════════════════════════════════════════════════════════════════════

# Regex patterns for direct extraction (fast, no LLM needed)
UPI_PATTERN = re.compile(r"[\w.\-+]+@(?:okaxis|oksbi|okicici|okhdfcbank|paytm|ybl|ibl|upi|gpay|phonepe|apl|axl|waicici)\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?:\+91|91)?[6-9]\d{9}")
ACCOUNT_PATTERN = re.compile(r"\b\d{9,18}\b")
IFSC_PATTERN = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
URL_PATTERN = re.compile(r"https?://[^\s]+")

EXTRACTOR_SYSTEM = """You are an intelligence extraction AI. From the scammer's message, extract:
- Any UPI IDs (format: name@bank)
- Phone numbers
- Bank names mentioned
- Account numbers
- Names of people
- Any suspicious URLs

Respond ONLY with JSON:
{
  "upi_ids": [],
  "phone_numbers": [],
  "bank_names": [],
  "account_numbers": [],
  "names": [],
  "urls": [],
  "raw_snippets": ["notable evidence phrases"]
}
"""


def extractor_node(state: HoneypotState) -> dict:
    """Extract UPI IDs, phone numbers, bank details from scammer's message."""
    message = state.current_scammer_message

    # --- Fast regex extraction ---
    upi_ids = list(set(UPI_PATTERN.findall(message)))
    phones = list(set(PHONE_PATTERN.findall(message)))
    accounts = list(set(ACCOUNT_PATTERN.findall(message)))
    urls = list(set(URL_PATTERN.findall(message)))

    # --- LLM extraction for names, bank names, context ---
    raw, _ = llm.chat(EXTRACTOR_SYSTEM, message, json_mode=True)
    llm_data = llm.parse_json_response(raw)

    # Merge regex + LLM results
    all_upi = list(set(upi_ids + llm_data.get("upi_ids", [])))
    all_phones = list(set(phones + [p.replace("+91", "").replace("91", "") for p in llm_data.get("phone_numbers", []) + phones]))
    all_accounts = list(set(accounts + llm_data.get("account_numbers", [])))
    all_urls = list(set(urls + llm_data.get("urls", [])))

    # Merge with existing intel (accumulate across turns)
    existing = state.intel
    updated_intel = ExtractedIntel(
        upi_ids=list(set(existing.upi_ids + all_upi)),
        phone_numbers=list(set(existing.phone_numbers + all_phones)),
        bank_names=list(set(existing.bank_names + llm_data.get("bank_names", []))),
        account_numbers=list(set(existing.account_numbers + all_accounts)),
        urls=list(set(existing.urls + all_urls)),
        names=list(set(existing.names + llm_data.get("names", []))),
        raw_snippets=existing.raw_snippets + llm_data.get("raw_snippets", []),
    )

    # Score how much intel we've collected (0.0 - 1.0)
    score = _calculate_intel_score(updated_intel)

    return {
        "intel": updated_intel,
        "intel_yield_score": score,
    }


def _calculate_intel_score(intel: ExtractedIntel) -> float:
    """Higher-value intel items score more points."""
    score = 0.0
    score += min(len(intel.upi_ids) * 0.3, 0.6)       # UPI IDs are gold
    score += min(len(intel.phone_numbers) * 0.15, 0.3)
    score += min(len(intel.account_numbers) * 0.1, 0.2)
    score += min(len(intel.bank_names) * 0.05, 0.1)
    return min(score, 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 5 — GUARD (Should we continue or end the session?)
# ═══════════════════════════════════════════════════════════════════════════════

def guard_node(state: HoneypotState) -> dict:
    """Decide if the honeypot session should continue or terminate."""
    reasons = []

    if state.turn_count >= state.max_turns:
        reasons.append(f"Max turns ({state.max_turns}) reached")

    if state.engagement_strategy == "terminate":
        reasons.append("Strategy node decided to terminate")

    if state.intel_yield_score >= 0.85:
        reasons.append(f"Intel yield is high ({state.intel_yield_score:.2f}) — mission complete")

    if state.threat_level == "low" and state.turn_count > 5 and state.confidence_score < 0.3:
        reasons.append("Low-confidence non-scam conversation after 5 turns")

    should_continue = len(reasons) == 0
    return {
        "should_continue": should_continue,
        "termination_reason": "; ".join(reasons) if reasons else "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTING FUNCTION — Used by LangGraph conditional edges
# ═══════════════════════════════════════════════════════════════════════════════

def route_after_guard(state: HoneypotState) -> str:
    """LangGraph routing: continue conversation or end."""
    return "continue" if state.should_continue else "end"


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _format_recent_messages(messages: list, n: int = 6) -> str:
    """Format last N messages for context injection."""
    recent = messages[-n:] if len(messages) > n else messages
    lines = []
    for msg in recent:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))
        prefix = "SCAMMER" if role == "human" else "BOT"
        lines.append(f"{prefix}: {content}")
    return "\n".join(lines) if lines else "(no history yet)"
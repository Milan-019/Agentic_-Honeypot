"""
Core state schema for the Agentic Honeypot LangGraph pipeline.
This is the single source of truth that flows through every node.
"""

from typing import Annotated, Literal, Optional
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages


# ── Scam Classification ─────────────────────────────────────────────────────

ScamType = Literal[
    "upi_fraud",
    "phishing",
    "fake_lottery",
    "job_scam",
    "romance_scam",
    "tech_support",
    "unknown",
]

ThreatLevel = Literal["low", "medium", "high", "critical"]

EngagementStrategy = Literal[
    "play_dumb",       # Feign confusion, ask basic questions
    "stall",           # Delay with excuses (no phone, slow internet, etc.)
    "request_info",    # Actively fish for scammer's bank/UPI details
    "escalate",        # Push scammer to reveal more by showing eagerness
    "terminate",       # End conversation (scammer went cold / too suspicious)
]

PersonaState = Literal[
    "naive_victim",      # Elderly/first-time user persona
    "cautiously_interested",  # Curious but hesitant
    "eager_victim",      # Appears ready to send money
]


# ── Intelligence Harvested ───────────────────────────────────────────────────

class ExtractedIntel(BaseModel):
    upi_ids: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    bank_names: list[str] = Field(default_factory=list)
    account_numbers: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    raw_snippets: list[str] = Field(default_factory=list)  # raw evidence


# ── Main Graph State ─────────────────────────────────────────────────────────

class HoneypotState(BaseModel):
    """
    The complete state object passed between all LangGraph nodes.
    Every field is optional to allow partial updates per node.
    """

    # --- Conversation ---
    session_id: str = ""
    messages: Annotated[list, add_messages] = Field(default_factory=list)
    current_scammer_message: str = ""
    turn_count: int = 0
    max_turns: int = 20  # Safety cap to prevent infinite loops

    # --- Classification (set by intake_node) ---
    scam_type: ScamType = "unknown"
    threat_level: ThreatLevel = "low"
    confidence_score: float = 0.0
    scam_indicators: list[str] = Field(default_factory=list)

    # --- Strategy (set by strategy_node) ---
    engagement_strategy: EngagementStrategy = "play_dumb"
    strategy_reasoning: str = ""
    persona: PersonaState = "naive_victim"

    # --- Response (set by persona_node) ---
    bot_response: str = ""

    # --- Intelligence (updated by extractor_node) ---
    intel: ExtractedIntel = Field(default_factory=ExtractedIntel)
    intel_yield_score: float = 0.0  # 0.0 to 1.0, how much we've harvested

    # --- Session Control (set by guard_node) ---
    should_continue: bool = True
    termination_reason: str = ""

    # --- Metadata ---
    model_used: str = ""
    total_time_wasted_seconds: float = 0.0

    class Config:
        arbitrary_types_allowed = True
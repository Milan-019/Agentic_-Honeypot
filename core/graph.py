"""
LangGraph graph assembly for the Agentic Honeypot.

Graph topology (DAG):
  START
    ↓
  intake_node        ← classify scammer message
    ↓
  strategy_node      ← decide engagement strategy
    ↓
  persona_node       ← generate in-character victim reply
    ↓
  extractor_node     ← harvest UPI IDs, phones, bank details
    ↓
  guard_node         ← should we continue or end?
    ↓ (conditional)
  [continue] → END (caller sends bot_response, loops on next turn)
  [end]      → END (session closed, final intel report generated)
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from core.state import HoneypotState
from core.nodes import (
    intake_node,
    strategy_node,
    persona_node,
    extractor_node,
    guard_node,
    route_after_guard,
)


def build_graph(use_memory: bool = True):
    """
    Build and compile the Agentic Honeypot LangGraph.
    
    Args:
        use_memory: If True, attaches MemorySaver for session persistence.
                    Set False for stateless single-turn usage.
    
    Returns:
        Compiled LangGraph app.
    """
    builder = StateGraph(HoneypotState)

    # ── Register all nodes ──────────────────────────────────────────────────
    builder.add_node("intake", intake_node)
    builder.add_node("strategy", strategy_node)
    builder.add_node("persona", persona_node)
    builder.add_node("extractor", extractor_node)
    builder.add_node("guard", guard_node)

    # ── Define edges (execution order) ─────────────────────────────────────
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "strategy")
    builder.add_edge("strategy", "persona")
    builder.add_edge("persona", "extractor")
    builder.add_edge("extractor", "guard")

    # Conditional exit: continue loop OR end session
    builder.add_conditional_edges(
        "guard",
        route_after_guard,
        {
            "continue": END,   # Caller handles looping (send next message)
            "end": END,        # Final turn — session closes
        },
    )

    # ── Compile ─────────────────────────────────────────────────────────────
    checkpointer = MemorySaver() if use_memory else None
    return builder.compile(checkpointer=checkpointer)


# Module-level singleton for import convenience
honeypot_graph = build_graph(use_memory=True)
from typing import Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from backend.graph.state import WeatherBotState
from backend.graph.nodes import (
    parse_user_query_node,
    resolve_location_node,
    location_error_node,
    fetch_weather_node,
    weather_error_node,
    evaluate_policies_node,
    no_sop_node,
    compose_response_node
)
from backend.graph.edges import (
    route_after_location,
    route_after_weather,
    route_after_policy
)
from backend.utils.logging_config import logger

def build_weather_bot_graph(checkpointer: Optional[MemorySaver] = None) -> Any:
    """
    Constructs and compiles the full LangGraph StateGraph with conditional branching
    and session-level memory checkpointing.
    """
    workflow = StateGraph(WeatherBotState)

    # 1. Add Nodes
    workflow.add_node("parse_user_query", parse_user_query_node)
    workflow.add_node("resolve_location", resolve_location_node)
    workflow.add_node("location_error", location_error_node)
    workflow.add_node("fetch_weather", fetch_weather_node)
    workflow.add_node("weather_error", weather_error_node)
    workflow.add_node("evaluate_policies", evaluate_policies_node)
    workflow.add_node("no_sop", no_sop_node)
    workflow.add_node("compose_response", compose_response_node)

    # 2. Add Standard Edges
    workflow.add_edge(START, "parse_user_query")
    workflow.add_edge("parse_user_query", "resolve_location")

    # 3. Add Conditional Edge: After Location Resolution
    workflow.add_conditional_edges(
        "resolve_location",
        route_after_location,
        {
            "fetch_weather": "fetch_weather",
            "location_error": "location_error"
        }
    )
    workflow.add_edge("location_error", END)

    # 4. Add Conditional Edge: After Weather Fetch
    workflow.add_conditional_edges(
        "fetch_weather",
        route_after_weather,
        {
            "evaluate_policies": "evaluate_policies",
            "weather_error": "weather_error"
        }
    )
    workflow.add_edge("weather_error", END)

    # 5. Add Conditional Edge: After Deterministic Policy Evaluation
    workflow.add_conditional_edges(
        "evaluate_policies",
        route_after_policy,
        {
            "compose_response": "compose_response",
            "no_sop": "no_sop"
        }
    )
    workflow.add_edge("compose_response", END)
    workflow.add_edge("no_sop", END)

    # Compile with memory checkpointer
    memory = checkpointer if checkpointer is not None else MemorySaver()
    app = workflow.compile(checkpointer=memory)
    logger.info("LangGraph WeatherBot StateGraph compiled successfully with checkpointing.")
    return app

# Singleton compiled graph with in-memory checkpointer
global_checkpointer = MemorySaver()
weather_bot_app = build_weather_bot_graph(global_checkpointer)

async def run_weather_bot(
    user_question: str, 
    session_id: str = "default",
    app: Optional[Any] = None
) -> WeatherBotState:
    """
    Executes the LangGraph agent for a given user query and session_id.
    Maintains conversation memory across turns with the same session_id.
    """
    target_app = app or weather_bot_app
    config = {"configurable": {"thread_id": session_id}}

    # Initialize state for this step without wiping existing messages checkpoint
    initial_input = {
        "user_question": user_question,
        "session_id": session_id,
    }

    result = await target_app.ainvoke(initial_input, config=config)
    return result

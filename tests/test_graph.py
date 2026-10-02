import pytest
from langgraph.checkpoint.memory import MemorySaver
from backend.graph.workflow import build_weather_bot_graph, run_weather_bot
from backend.models.schemas import WeatherFacts
from backend.services.weather_service import weather_service

@pytest.fixture(autouse=True)
def clean_mocks():
    weather_service.set_mock_failure(False)
    weather_service.set_mock_weather(None)
    yield
    weather_service.set_mock_failure(False)
    weather_service.set_mock_weather(None)

def test_graph_compilation():
    mem = MemorySaver()
    app = build_weather_bot_graph(checkpointer=mem)
    assert app is not None
    # Check that required nodes exist
    node_names = set(app.nodes.keys())
    expected_nodes = {
        "parse_user_query",
        "resolve_location",
        "location_error",
        "fetch_weather",
        "weather_error",
        "evaluate_policies",
        "no_sop",
        "compose_response"
    }
    assert expected_nodes.issubset(node_names)

@pytest.mark.asyncio
async def test_graph_happy_path_execution():
    weather_service.set_mock_weather(WeatherFacts(
        temperature_c=26.0,
        wind_speed_kmh=45.0,
        precipitation_mm=0.0,
        precipitation_probability=0.0,
        uv_index=4.0,
        timestamp="2026-10-01T12:00",
        time_context="today"
    ))
    res = await run_weather_bot("Is it safe to cycle in Bhopal today?", session_id="test_happy")
    assert res.get("status") == "success"
    assert res.get("selected_sop") is not None
    assert res.get("selected_sop", {}).get("id") == "SOP-001"
    assert "response" in res
    assert len(res["response"]) > 0

@pytest.mark.asyncio
async def test_graph_session_isolation():
    # Session A: cycling in Bhopal
    await run_weather_bot("Is it safe to cycle in Bhopal today?", session_id="sess_A")
    
    # Session B: running in Mumbai
    res_b = await run_weather_bot("Is it safe to run in Mumbai today?", session_id="sess_B")
    assert res_b.get("location", {}).get("city") == "Mumbai"
    assert res_b.get("intent", {}).get("activity") == "running"

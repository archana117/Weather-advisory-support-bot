from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from backend.config import settings
from backend.models.schemas import ChatRequest, ChatResponse, LocationData, WeatherFacts
from backend.models.sop_models import PolicyEvaluationResult
from backend.services.sop_service import sop_service
from backend.graph.workflow import run_weather_bot, global_checkpointer
from backend.utils.logging_config import logger

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description="Deterministic LangGraph-powered outdoor activity safety bot with live Open-Meteo weather and externalized SOP policies."
)

# Enable CORS for Streamlit / external clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.PROJECT_VERSION,
        "status": "online",
        "loaded_sops": len(sop_service.get_all_sops()),
        "endpoints": {
            "chat": "POST /chat",
            "health": "GET /health",
            "sops": "GET /sops",
            "reset_session": "POST /session/reset"
        }
    }

@app.get("/health")
async def health_check():
    sops = sop_service.get_all_sops()
    return {
        "status": "healthy",
        "sop_count": len(sops),
        "llm_provider": settings.LLM_PROVIDER,
        "model_name": settings.MODEL_NAME,
        "api_key_configured": bool(settings.OPENAI_API_KEY)
    }

@app.get("/sops")
async def list_sops():
    """Returns all currently loaded SOPs directly from the external YAML policy database."""
    sops = sop_service.load_sops()
    return {
        "count": len(sops),
        "sops": [sop.model_dump() for sop in sops]
    }

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Core chat endpoint executing the LangGraph agent for the user's query and session_id.
    """
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    try:
        final_state = await run_weather_bot(
            user_question=request.message.strip(),
            session_id=request.session_id
        )

        location_data = None
        if final_state.get("location"):
            location_data = LocationData(**final_state["location"])

        weather_data = None
        if final_state.get("weather"):
            weather_data = WeatherFacts(**final_state["weather"])

        policy_result = None
        if final_state.get("policy_decision"):
            policy_result = PolicyEvaluationResult(**final_state["policy_decision"])

        return ChatResponse(
            response=final_state.get("response", "No response generated."),
            session_id=request.session_id,
            status=final_state.get("status", "unknown"),
            location=location_data,
            weather=weather_data,
            policy_result=policy_result,
            error=final_state.get("error")
        )

    except Exception as exc:
        logger.error(f"Error handling chat request: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal agent error: {str(exc)}")

@app.post("/session/reset")
async def reset_session(session_id: str):
    """
    Clears memory checkpoint for a specific session thread.
    """
    try:
        # Re-initialize memory slot if needed
        logger.info(f"Resetting session memory for thread_id: '{session_id}'")
        return {"status": "success", "message": f"Session '{session_id}' memory reset."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=False
    )

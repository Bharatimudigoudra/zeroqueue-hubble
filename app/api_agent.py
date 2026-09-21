"""Agent console API: list handoffs, review the AI draft, reply or add a note."""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app import config
from app.services import agent_console

router = APIRouter()


class AgentMessage(BaseModel):
    body: str


def _authorize(x_agent_key: str) -> None:
    """Optional protection, enforced only when AGENT_CONSOLE_KEY is set."""
    if config.AGENT_CONSOLE_KEY and x_agent_key != config.AGENT_CONSOLE_KEY:
        raise HTTPException(status_code=403, detail="agent key required")


def _clean_body(body: str) -> str:
    cleaned = (body or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="body is required.")
    return cleaned


@router.get("/api/agent/conversations")
def list_conversations(x_agent_key: str = Header(default="")):
    _authorize(x_agent_key)
    return agent_console.list_conversations()


@router.get("/api/agent/conversations/{session_id}")
def conversation_detail(session_id: str, x_agent_key: str = Header(default="")):
    _authorize(x_agent_key)
    detail = agent_console.conversation_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="unknown session")
    return detail


@router.post("/api/agent/conversations/{session_id}/reply")
def approve_reply(session_id: str, message: AgentMessage,
                  x_agent_key: str = Header(default="")):
    _authorize(x_agent_key)
    result = agent_console.approve_reply(session_id, _clean_body(message.body))
    if result.get("reason") == "unknown_session":
        raise HTTPException(status_code=404, detail="unknown session")
    return result


@router.post("/api/agent/conversations/{session_id}/note")
def internal_note(session_id: str, message: AgentMessage,
                  x_agent_key: str = Header(default="")):
    _authorize(x_agent_key)
    result = agent_console.add_internal_note(session_id, _clean_body(message.body))
    if result.get("reason") == "unknown_session":
        raise HTTPException(status_code=404, detail="unknown session")
    return result

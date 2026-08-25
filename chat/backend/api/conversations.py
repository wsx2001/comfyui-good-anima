"""Conversation CRUD endpoints.

Step 1: basic CRUD + list. No streaming, no LLM involvement yet.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.storage.db import get_session
from backend.storage.models import Conversation, Message
from backend.utils.id_gen import new_id

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ConversationCreate(BaseModel):
    title: Optional[str] = None
    default_workflow_id: Optional[str] = "local/anima-txt2img-aesthetic-lora"
    default_params: Optional[dict] = None


class ConversationPatch(BaseModel):
    title: Optional[str] = None
    default_workflow_id: Optional[str] = None
    default_params: Optional[dict] = None


class ConversationSummary(BaseModel):
    id: str
    title: str
    default_workflow_id: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, c: Conversation) -> "ConversationSummary":
        return cls(
            id=c.id,
            title=c.title,
            default_workflow_id=c.default_workflow_id,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )


class ConversationDetail(ConversationSummary):
    messages: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/conversations")
def list_conversations(session: Session = Depends(get_session)) -> list[ConversationSummary]:
    rows = session.exec(
        select(Conversation).order_by(Conversation.updated_at.desc())
    ).all()
    return [ConversationSummary.from_model(c).model_dump() for c in rows]


@router.post("/conversations", status_code=201)
def create_conversation(
    body: ConversationCreate = ConversationCreate(),
    session: Session = Depends(get_session),
) -> dict:
    now = datetime.utcnow()
    conv = Conversation(
        id=new_id(),
        title=body.title or "新会话",
        created_at=now,
        updated_at=now,
        default_workflow_id=body.default_workflow_id or "local/anima-txt2img-aesthetic-lora",
        default_params=None,
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return ConversationSummary.from_model(conv).model_dump()


@router.get("/conversations/{conv_id}")
def get_conversation(
    conv_id: str,
    session: Session = Depends(get_session),
) -> dict:
    conv = session.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = session.exec(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    ).all()
    return {
        **ConversationSummary.from_model(conv).model_dump(),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "reasoning": m.reasoning,
                "job_id": m.job_id,
                "created_at": m.created_at.isoformat(),
            }
            for m in msgs
        ],
    }


@router.patch("/conversations/{conv_id}")
def patch_conversation(
    conv_id: str,
    body: ConversationPatch,
    session: Session = Depends(get_session),
) -> dict:
    conv = session.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if body.title is not None:
        conv.title = body.title
    if body.default_workflow_id is not None:
        conv.default_workflow_id = body.default_workflow_id
    if body.default_params is not None:
        import json

        conv.default_params = json.dumps(body.default_params, ensure_ascii=False)
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()
    return {"ok": True, "conversation": ConversationSummary.from_model(conv).model_dump()}


@router.delete("/conversations/{conv_id}", status_code=200)
def delete_conversation(
    conv_id: str,
    session: Session = Depends(get_session),
) -> dict:
    conv = session.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Cascade: drop messages too. Jobs/Images stay (they reference conversations
    # by id only, no FK cascade here).
    for m in session.exec(select(Message).where(Message.conversation_id == conv_id)).all():
        session.delete(m)
    session.delete(conv)
    session.commit()
    return {"ok": True}
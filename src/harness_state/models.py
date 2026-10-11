"""Módulos de dados e esquemas para State Tracking na plataforma SDD."""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class TaskState(str, Enum):
    """Estado do ciclo de vida de uma sub-tarefa em um repositório alvo."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    APPROVED = "APPROVED"
    FAILED = "FAILED"


class SubTask(BaseModel):
    """Sub-tarefa decomposta para um repositório específico."""
    id: str
    repo: str
    branch: str
    status: TaskState = TaskState.PENDING
    pr_number: Optional[int] = None
    sub_spec_path: Optional[str] = None
    last_worker: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SpecRun(BaseModel):
    """Estado global de uma especificação no barramento central."""
    spec_id: str
    title: str
    author: str
    status: TaskState = TaskState.IN_PROGRESS
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tasks: Dict[str, SubTask] = Field(default_factory=dict)
    correlation_uuid: Optional[str] = None

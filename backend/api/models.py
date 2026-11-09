"""Pydantic schemas for Vagamundo v2 API."""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    token: str


class SearchRequest(BaseModel):
    priority: Optional[List[int]] = Field(default_factory=list, alias="priorities")
    jobage: int = 14
    focus: str = "all"
    portals: Optional[List[str]] = None
    region: str = "all"
    all: bool = False
    query: Optional[str] = None

    class Config:
        populate_by_name = True


class SearchProgress(BaseModel):
    percent: float = 0.0
    completed: int = 0
    total: int = 0
    current_portal: Optional[str] = None
    jobs_found: int = 0
    portals: Dict[str, Any] = Field(default_factory=dict)


class SearchStatusResponse(BaseModel):
    running: bool
    started: Optional[str] = None
    error: Optional[str] = None
    summary: Optional[str] = None
    progress: Optional[SearchProgress] = None
    batch: Optional[Dict[str, Any]] = None


class MarkRequest(BaseModel):
    urls: Optional[List[str]] = Field(default_factory=list)
    ids: Optional[List[str]] = Field(default_factory=list)
    decision: str = "interested"
    job_data: Optional[Dict[str, Any]] = None


class SingleUrlRequest(BaseModel):
    url: str


class ApplicationRemoveRequest(BaseModel):
    url: Optional[str] = None
    id: Optional[int] = None
    job_id: Optional[str] = None


class BatchScreenRequest(BaseModel):
    urls: List[str]


class EvaluateRequest(BaseModel):
    ids: Optional[List[str]] = Field(default_factory=list)
    urls: Optional[List[str]] = Field(default_factory=list)


class SettingsSaveRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    key: Optional[str] = None
    base_url: Optional[str] = None
    claude_mode: Optional[str] = None
    openai_key: Optional[str] = None
    openai_model: Optional[str] = None
    openai_base_url: Optional[str] = None
    gemini_key: Optional[str] = None
    gemini_model: Optional[str] = None
    anthropic_key: Optional[str] = None
    anthropic_model: Optional[str] = None


class ClaudeStepRequest(BaseModel):
    step: str
    url: Optional[str] = None
    confirm: bool = False


class UploadFileRequest(BaseModel):
    kind: str
    name: str
    data: str  # base64 encoded data URI or string


class RemoveUploadRequest(BaseModel):
    kind: str
    name: str


class ApplicationSaveRequest(BaseModel):
    url: Optional[str] = None
    job_id: Optional[str] = None
    title: Optional[str] = None
    role: Optional[str] = None
    company: Optional[str] = None
    portal: Optional[str] = None
    date: Optional[str] = None
    applied_date: Optional[str] = None
    status: str = "applied"
    cv_file: Optional[str] = None
    cover_letter_file: Optional[str] = None
    notes: Optional[str] = None
    event_date: Optional[str] = None
    event_stage: Optional[str] = None
    event_feedback: Optional[str] = None
    event_questions_and_answers: Optional[str] = None



class AppliedRequest(BaseModel):
    url: str
    company: Optional[str] = ''
    role: Optional[str] = ''
    portal: Optional[str] = ''


class ApplicationEventCreateRequest(BaseModel):
    application_id: Optional[int] = None
    job_id: Optional[str] = None
    url: Optional[str] = None
    stage: str
    event_date: Optional[str] = None
    feedback: Optional[str] = None
    questions_and_answers: Optional[str] = None
    status: Optional[str] = None


class PasteRecruiterPostRequest(BaseModel):
    raw_text: str
    url: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    work_model: Optional[str] = None

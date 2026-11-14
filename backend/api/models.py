"""Pydantic schemas for Vagamundo v2 API."""

from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class TokenResponse(BaseModel):
    token: str


class SearchRequest(BaseModel):
    priority: Optional[List[int]] = Field(default_factory=list, alias="priorities")
    jobage: int = Field(default=14, ge=1, le=365)
    focus: str = "all"
    portals: Optional[List[str]] = None
    region: str = "all"
    all: bool = False
    query: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


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


class ProviderSettingsInput(BaseModel):
    model: Optional[str] = None
    api_key: Optional[str] = None
    clear_key: Optional[bool] = None
    base_url: Optional[str] = None


class SettingsSaveRequest(BaseModel):
    provider: Optional[str] = None
    consent: Optional[bool] = None
    providers: Optional[Dict[str, ProviderSettingsInput]] = None
    model: Optional[str] = None
    key: Optional[str] = None
    base_url: Optional[str] = None
    claude_mode: Optional[str] = None
    openai_key: Optional[str] = None
    openai_model: Optional[str] = None
    openai_base_url: Optional[str] = None
    gemini_key: Optional[str] = None
    gemini_model: Optional[str] = None
    claude_key: Optional[str] = None
    anthropic_key: Optional[str] = None
    anthropic_model: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class ProfileSaveRequest(BaseModel):
    answers: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")

    def to_answers_dict(self) -> Dict[str, Any]:
        """Extract questionnaire fields whether nested under `answers` or sent flat."""
        if isinstance(self.answers, dict):
            return self.answers
        return self.model_dump(exclude={"answers"})


class ProfileOrganizeRequest(BaseModel):
    overwrite: bool = False
    confirm: bool = False


class ClaudeStepRequest(BaseModel):
    step: Literal["perfil", "avaliar", "curriculo", "carta", "redigir", "entrevista"]
    url: Optional[str] = None


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
    contact_channel: Optional[str] = None
    contacted_email: Optional[str] = None


class BatchAppliedRequest(BaseModel):
    items: List[AppliedRequest]


class RecruiterContactedRequest(BaseModel):
    email: Optional[str] = None
    notes: Optional[str] = None


class ReopenRecruiterRequest(BaseModel):
    id: Optional[int] = None
    job_id: Optional[str] = None
    url: Optional[str] = None
    recruiter_post_id: Optional[int] = None


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
    published_date: Optional[str] = None


class PasteRecruiterBatchItem(BaseModel):
    raw_text: str
    url: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    work_model: Optional[str] = None
    published_date: Optional[str] = None


class PasteRecruiterBatchRequest(BaseModel):
    items: Optional[List[PasteRecruiterBatchItem]] = None
    raw_batch_text: Optional[str] = None


class AutoModeStartRequest(BaseModel):
    region: Optional[str] = None
    portals: Optional[List[str]] = None
    jobage: Optional[int] = None
    min_score: Optional[int] = None
    hide_undated: Optional[bool] = None
    continuous: Optional[bool] = None
    cooldown_seconds: Optional[int] = None


class AutoModeConfigRequest(BaseModel):
    region: Optional[str] = None
    portals: Optional[List[str]] = None
    jobage: Optional[int] = None
    min_score: Optional[int] = None
    hide_undated: Optional[bool] = None
    continuous: Optional[bool] = None
    cooldown_seconds: Optional[int] = None


class AutoModeUndoRequest(BaseModel):
    run_id: Optional[str] = None


class AutoModeUndoJobRequest(BaseModel):
    url: Optional[str] = None
    job_id: Optional[str] = None


class RecruiterAutoStartRequest(BaseModel):
    min_score: Optional[int] = None
    continuous: Optional[bool] = None
    cooldown_seconds: Optional[int] = None


class RecruiterAutoConfigRequest(BaseModel):
    min_score: Optional[int] = None
    continuous: Optional[bool] = None
    cooldown_seconds: Optional[int] = None


class LinkedInWorkerConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    headless: Optional[bool] = None
    cooldown_minutes: Optional[int] = None
    max_daily_searches: Optional[int] = None
    max_scrolls: Optional[int] = None


class RecruiterTriageRequest(BaseModel):
    post_ids: Optional[List[int]] = None
    q: Optional[str] = None
    portal: Optional[str] = None
    limit: int = 12


class RecruiterDismissBatchRequest(BaseModel):
    post_ids: List[int] = Field(default_factory=list)

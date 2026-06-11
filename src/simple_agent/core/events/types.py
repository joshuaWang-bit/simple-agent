from typing import Annotated, Any, Literal

from pydantic import BaseModel, Discriminator


class RunStartedEvent(BaseModel):
    type: Literal["run.started"] = "run.started"
    run_id: str
    goal: str
    ts: str


class RunFinishedEvent(BaseModel):
    type: Literal["run.finished"] = "run.finished"
    run_id: str
    status: str
    step_count: int
    elapsed_s: float
    reason: str | None = None
    ts: str


class StepStartedEvent(BaseModel):
    type: Literal["step.started"] = "step.started"
    run_id: str
    step: int
    ts: str


class StepFinishedEvent(BaseModel):
    type: Literal["step.finished"] = "step.finished"
    run_id: str
    step: int
    status: str
    ts: str


class LlmRequestEvent(BaseModel):
    type: Literal["llm.request"] = "llm.request"
    run_id: str
    model: str
    ts: str


class LlmTokenEvent(BaseModel):
    type: Literal["llm.token"] = "llm.token"
    run_id: str
    token: str
    ts: str


class LlmUsageEvent(BaseModel):
    type: Literal["llm.usage"] = "llm.usage"
    run_id: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    context_pct: float = 0.0
    ts: str


class ContextCompactedEvent(BaseModel):
    type: Literal["context.compacted"] = "context.compacted"
    run_id: str = ""
    session_id: str = ""
    original_tokens: int
    summary_tokens: int
    summary_path: str = ""
    persistent: bool = False
    ts: str


class SkillInvokedEvent(BaseModel):
    type: Literal["skill.invoked"] = "skill.invoked"
    session_id: str
    run_id: str
    skill_name: str
    arguments: str
    tool_whitelist: list[str] = []
    ts: str


class SubagentStartedEvent(BaseModel):
    type: Literal["subagent.started"] = "subagent.started"
    run_id: str
    parent_run_id: str
    description: str
    subagent_type: str = ""
    background: bool = False
    ts: str


class SubagentFinishedEvent(BaseModel):
    type: Literal["subagent.finished"] = "subagent.finished"
    run_id: str
    parent_run_id: str
    status: str
    elapsed_s: float
    reason: str | None = None
    ts: str


class ToolCallStartedEvent(BaseModel):
    type: Literal["tool.call_started"] = "tool.call_started"
    run_id: str
    tool_use_id: str
    tool_name: str
    input: dict[str, Any]
    ts: str


class ToolCallFinishedEvent(BaseModel):
    type: Literal["tool.call_finished"] = "tool.call_finished"
    run_id: str
    tool_use_id: str
    tool_name: str
    elapsed_ms: int
    output: str = ""
    is_error: bool = False
    ts: str


class ToolCallFailedEvent(BaseModel):
    type: Literal["tool.call_failed"] = "tool.call_failed"
    run_id: str
    tool_use_id: str
    tool_name: str
    error_class: str
    error_message: str
    attempt: int | None = None
    ts: str


class PermissionRequestedEvent(BaseModel):
    type: Literal["permission.requested"] = "permission.requested"
    run_id: str
    tool_use_id: str
    tool_name: str
    params: dict[str, Any]
    param_preview: str
    session_id: str
    ts: str


class SessionCreatedEvent(BaseModel):
    type: Literal["session.created"] = "session.created"
    session_id: str
    mode: str
    ts: str


class SessionMessageReceivedEvent(BaseModel):
    type: Literal["session.message_received"] = "session.message_received"
    session_id: str
    role: str
    content: str
    ts: str


class SessionResumedEvent(BaseModel):
    type: Literal["session.resumed"] = "session.resumed"
    session_id: str
    ts: str


class SessionWaitingForInputEvent(BaseModel):
    type: Literal["session.waiting_for_input"] = "session.waiting_for_input"
    session_id: str
    ts: str


class SessionClosedEvent(BaseModel):
    type: Literal["session.closed"] = "session.closed"
    session_id: str
    ts: str


Event = Annotated[
    RunStartedEvent
    | RunFinishedEvent
    | StepStartedEvent
    | StepFinishedEvent
    | LlmRequestEvent
    | LlmTokenEvent
    | LlmUsageEvent
    | ContextCompactedEvent
    | SkillInvokedEvent
    | SubagentStartedEvent
    | SubagentFinishedEvent
    | ToolCallStartedEvent
    | ToolCallFinishedEvent
    | ToolCallFailedEvent
    | PermissionRequestedEvent
    | SessionCreatedEvent
    | SessionMessageReceivedEvent
    | SessionResumedEvent
    | SessionWaitingForInputEvent
    | SessionClosedEvent,
    Discriminator("type"),
]

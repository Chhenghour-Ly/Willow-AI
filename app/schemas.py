from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


FACT_NAMES = ('farmer_name', 'crop', 'location', 'policy_number', 'discovery_date', 'acreage', 'damage_description')


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Fact(Strict):
    value: str | None = Field(default=None, max_length=4000)
    confirmed: bool = False
    sources: list[str] = Field(default_factory=list, max_length=20)


class AttachmentRef(Strict):
    document_id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1)


class VersionRequest(Strict):
    version: int = Field(ge=1)


class CasePatch(VersionRequest):
    facts: dict[str, Fact] | None = None
    draft_notice: str | None = Field(default=None, min_length=1, max_length=20000)
    recipient: str | None = Field(default=None, max_length=254)
    attachments: list[AttachmentRef] | None = Field(default=None, max_length=10)

    @field_validator('facts')
    @classmethod
    def known_fields(cls, value):
        if value and set(value) - set(FACT_NAMES):
            raise ValueError('Unknown fact fields')
        return value

    @field_validator('recipient')
    @classmethod
    def email(cls, value):
        if value is None:
            return value
        return validate_email(value)


def validate_email(value):
    import re
    if not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', value):
        raise ValueError('A single plain email address is required')
    return value.lower()


class TokenExchange(Strict):
    token: str = Field(min_length=20, max_length=200)


class SessionResponse(Strict):
    session_token: str
    case_id: str
    expires_in: int


class Requirement(Strict):
    text: str
    sources: list[str]
    applicability: Literal['unknown', 'applicable', 'not_applicable'] = 'unknown'
    reviewed: bool = False


class RagInput(Strict):
    facts: dict[str, Fact]
    crop: str | None
    location: str | None
    policy_identifiers: list[str]
    document_references: list[dict]
    missing_or_uncertain: list[str]


class RagOutput(Strict):
    requirements: list[Requirement]
    unresolved_questions: list[str]
    simulated: bool


class SubmissionResponse(Strict):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
    provider_id: str | None
    error: str | None
    simulated: bool
    acknowledged: bool


class CaseResponse(Strict):
    id: str
    facts: dict[str, Fact]
    missing_information: list[str]
    requirements: list[Requirement]
    unresolved_questions: list[str]
    rag_simulated: bool
    draft_notice: str | None
    recipient: str | None
    attachments: list[dict]
    draft_version: int
    approval_version: int | None
    processing_status: str
    submission: SubmissionResponse | None
    notification: dict | None
    tasks: list[dict]

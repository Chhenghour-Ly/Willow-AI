"""Turn a Vapi end-of-call report into a clean farmer profile.

Vapi delivers the "FarmBridge Farmer Profile" structured output at
message.artifact.structuredOutputs[<output id>].result (the call object from
GET /call/{id} carries the same artifact). Values Vapi could not hear arrive as
"unknown" or 0; both become None. Nothing is inferred beyond what was said.
"""
import re

from pydantic import BaseModel, Field

STATES = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA', 'colorado': 'CO',
    'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID',
    'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA',
    'maine': 'ME', 'maryland': 'MD', 'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN',
    'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
    'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC',
    'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA',
    'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX',
    'utah': 'UT', 'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV',
    'wisconsin': 'WI', 'wyoming': 'WY',
}
NEEDS = ('irrigation_upgrade', 'water_conservation', 'soil_health', 'financing', 'equipment', 'expansion',
         'crop_damage', 'long_term_conservation')
LAND_CONTROL = ('owned', 'leased', 'other')
PROJECT_STATUS = ('not_started', 'in_progress', 'completed')
FUNDING = ('nonrepayable_only', 'prefer_nonrepayable_open_to_loan', 'loan_ok')
# Fields that matching cannot start without; anything else missing becomes a follow-up question.
CORE_FIELDS = ('state', 'needs')


class FarmerProfile(BaseModel):
    call_id: str
    phone: str | None = None
    farmer_name: str | None = None
    state: str | None = None
    county: str | None = None
    crops: list[str] = Field(default_factory=list)
    primary_problem: str | None = None
    desired_project: str | None = None
    needs: list[str] = Field(default_factory=list)
    land_control: str | None = None
    project_status: str | None = None
    project_acres: float | None = None
    total_farm_acres: float | None = None
    total_project_cost_usd: float | None = None
    assistance_needed_usd: float | None = None
    funding_preference: str | None = None
    irrigated_years_of_last_5: int | None = None
    call_summary: str | None = None
    # Email delivery. Consent is True only for an explicit yes; anything else is None/False.
    deep_matching_requested: bool | None = None
    email_delivery_consent: bool | None = None
    results_email: str | None = None  # only a well-formed address the farmer confirmed on the call
    email_consent_statement: str | None = None
    sms_delivery_consent: bool | None = None
    sms_results_phone: str | None = None
    sms_consent_statement: str | None = None
    consent_at: str | None = None  # call end time from Vapi, the moment consent was last given
    source: str = 'none'  # structured_output | none

    def missing_core(self):
        return [f for f in CORE_FIELDS if not getattr(self, f)]

    def search_text(self):
        parts = [self.primary_problem, self.desired_project, ' '.join(self.needs), ' '.join(self.crops), self.call_summary]
        return ' '.join(p for p in parts if p).replace('_', ' ')


def text(value):
    value = value.strip() if isinstance(value, str) else ''
    return value if value and value.lower() not in ('unknown', 'none', 'n/a', 'null') else None


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        match = re.search(r'(\d[\d,]*\.?\d*)\s*(k|thousand|m|million)?\b', str(value or '').lower())
        if not match:
            return None
        result = float(match.group(1).replace(',', '')) * {'k': 1e3, 'thousand': 1e3, 'm': 1e6, 'million': 1e6}.get(match.group(2), 1)
    # Vapi sends 0 for numbers nobody said.
    return result if result > 0 else None


def items(value):
    raw = value if isinstance(value, list) else re.split(r',|;|\band\b', str(value or ''))
    out = []
    for item in raw:
        word = text(str(item))
        if word and word.lower() not in out:
            out.append(word.lower())
    return out


def explicit(value):
    """True only for an explicit yes. False for an explicit no. Everything else (missing, 'maybe') is None."""
    if isinstance(value, bool):
        return value
    word = (text(value) or '').lower()
    return True if word in ('true', 'yes') else False if word in ('false', 'no') else None


def email(value):
    """A single well-formed address, lowercased. Spoken fragments ('carolina at gmail') are rejected, not repaired."""
    address = (text(value) or '').lower()
    if len(address) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}", address):
        return None
    return address


def sms_phone(value):
    number = text(value)
    return number if number and re.fullmatch(r'\+[1-9]\d{1,14}', number) else None


def choice(value, allowed):
    word = (text(value) or '').lower().replace(' ', '_').replace('-', '_')
    return word if word in allowed else None


def state(value):
    raw = (text(value) or '').lower()
    if raw.upper() in STATES.values():
        return raw.upper()
    # Longest names first so "west virginia" wins over "virginia".
    for name in sorted(STATES, key=len, reverse=True):
        if re.search(rf'\b{name}\b', raw):
            return STATES[name]
    return None


def structured_data(message: dict) -> dict:
    """Merge every structured output in the event or call object (plus the legacy analysis location)."""
    data = dict((message.get('analysis') or {}).get('structuredData') or {})
    for holder in (message, message.get('call') or {}):
        for output in ((holder.get('artifact') or {}).get('structuredOutputs') or {}).values():
            if isinstance(output, dict) and isinstance(output.get('result'), dict):
                data.update(output['result'])
    return data


def transcript_of(message: dict) -> str:
    for holder in (message, message.get('call') or {}):
        artifact = holder.get('artifact') or {}
        if artifact.get('transcript'):
            return artifact['transcript']
        lines = [f"{m.get('role')}: {m.get('message')}" for m in artifact.get('messages') or []
                 if m.get('role') in ('user', 'bot', 'assistant') and m.get('message')]
        if lines:
            return '\n'.join(lines)
    return message.get('transcript') or ''


def call_id_of(payload: dict) -> str:
    message = payload.get('message') if isinstance(payload, dict) else None
    call = message.get('call') if isinstance(message, dict) else None
    call_id = call.get('id') if isinstance(call, dict) else None
    if not isinstance(call_id, str) or not 1 <= len(call_id) <= 200:
        raise ValueError('Missing call id')
    return call_id


def extract_profile(payload: dict) -> FarmerProfile:
    message = payload['message']
    data = structured_data(message)
    customer = (message.get('call') or {}).get('customer') or message.get('customer') or {}
    irrigated = number(data.get('irrigated_years_of_last_5'))
    return FarmerProfile(
        call_id=call_id_of(payload),
        phone=text(customer.get('number')),
        farmer_name=text(data.get('farmer_name')),
        state=state(data.get('state')),
        county=text(data.get('county')),
        crops=items(data.get('crops')),
        primary_problem=text(data.get('primary_problem')),
        desired_project=text(data.get('desired_project')),
        needs=[n for n in items(data.get('needs')) if n in NEEDS],
        land_control=choice(data.get('land_control'), LAND_CONTROL),
        project_status=choice(data.get('project_status'), PROJECT_STATUS),
        project_acres=number(data.get('project_acres')),
        total_farm_acres=number(data.get('total_farm_acres')),
        total_project_cost_usd=number(data.get('total_project_cost_usd')),
        assistance_needed_usd=number(data.get('assistance_needed_usd')),
        funding_preference=choice(data.get('funding_preference'), FUNDING),
        irrigated_years_of_last_5=int(irrigated) if irrigated and irrigated <= 5 else None,
        call_summary=text(data.get('call_summary')) or text(message.get('summary')),
        deep_matching_requested=explicit(data.get('deep_matching_requested')),
        email_delivery_consent=explicit(data.get('email_delivery_consent')),
        results_email=email(data.get('results_email')),
        email_consent_statement=text(data.get('email_consent_statement')),
        sms_delivery_consent=explicit(data.get('sms_delivery_consent')),
        sms_results_phone=sms_phone(data.get('sms_results_phone')),
        sms_consent_statement=text(data.get('sms_consent_statement')),
        consent_at=text(message.get('endedAt')) or text((message.get('call') or {}).get('endedAt')),
        source='structured_output' if data else 'none',
    )

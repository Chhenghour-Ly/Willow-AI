"""Turn a Vapi end-of-call report into a clean farmer profile.

Field names under analysis.structuredData are our proposal to the voice-agent
teammate. Swap the paths here once a real captured payload is available.
"""
import re
from datetime import date

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

CROP_ALIASES = {
    'soybean': 'soybeans', 'soy': 'soybeans', 'beans': 'soybeans', 'apple': 'apples', 'cow': 'cattle',
    'cows': 'cattle', 'beef': 'cattle', 'bees': 'honeybees', 'grape': 'grapes', 'tomato': 'tomatoes',
    'vegetable': 'vegetables', 'veggies': 'vegetables', 'berry': 'berries', 'peach': 'peaches',
    'cherry': 'cherries', 'pig': 'hogs', 'pigs': 'hogs', 'goat': 'goats', 'nut': 'nuts',
}

# First match wins, so "hail storm" is hail, not wind.
DAMAGE_WORDS = [
    ('hail', 'hail'), ('drought', 'drought'), ('dry', 'drought'), ('flood', 'flood'), ('freeze', 'freeze'),
    ('frost', 'freeze'), ('fire', 'fire'), ('tornado', 'wind'), ('derecho', 'wind'), ('wind', 'wind'),
    ('storm', 'wind'), ('rain', 'excess_moisture'), ('moisture', 'excess_moisture'), ('wet', 'excess_moisture'),
    ('disease', 'disease'), ('blight', 'disease'), ('insect', 'insects'), ('pest', 'insects'),
]


class FarmerProfile(BaseModel):
    call_id: str
    phone: str | None = None
    farmer_name: str | None = None
    state: str | None = None
    county: str | None = None
    crops: list[str] = Field(default_factory=list)
    damage_type: str | None = None
    acres_damaged: float | None = None
    total_acres: float | None = None
    loss_percent: float | None = None
    loss_date: date | None = None
    annual_income: float | None = None
    has_crop_insurance: bool | None = None
    years_farming: float | None = None
    is_organic: bool | None = None
    story: str = ''


def text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    match = re.search(r'(\d[\d,]*\.?\d*)\s*(k|thousand|m|million)?\b', str(value or '').lower())
    if not match:
        return None
    result = float(match.group(1).replace(',', ''))
    scale = {'k': 1e3, 'thousand': 1e3, 'm': 1e6, 'million': 1e6}.get(match.group(2), 1)
    result *= scale
    return int(result) if result.is_integer() else result


def yes_no(value):
    if isinstance(value, bool):
        return value
    word = str(value or '').strip().lower()
    if word in ('yes', 'y', 'true', 'yeah', 'yep'):
        return True
    if word in ('no', 'n', 'false', 'nope'):
        return False
    return None


def state(value):
    raw = (text(value) or '').lower()
    if raw.upper() in STATES.values():
        return raw.upper()
    # Longest names first so "west virginia" wins over "virginia".
    for name in sorted(STATES, key=len, reverse=True):
        if re.search(rf'\b{name}\b', raw):
            return STATES[name]
    return None


def crops(value):
    items = value if isinstance(value, list) else re.split(r',|&|/|\band\b', str(value or ''))
    result = []
    for item in items:
        word = re.sub(r'\b(some|a little|a few|of)\b', '', str(item).lower()).strip()
        word = CROP_ALIASES.get(word, word)
        if word and word not in result:
            result.append(word)
    return result


def damage_type(value):
    raw = str(value or '').lower()
    return next((kind for word, kind in DAMAGE_WORDS if word in raw), None)


def iso_date(value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def extract_profile(payload: dict) -> FarmerProfile:
    message = payload.get('message') if isinstance(payload, dict) else None
    call = message.get('call') if isinstance(message, dict) else None
    call_id = call.get('id') if isinstance(call, dict) else None
    if not isinstance(call_id, str) or not 1 <= len(call_id) <= 200:
        raise ValueError('Missing call id')
    analysis = message.get('analysis') or {}
    data = analysis.get('structuredData') or {}
    transcript = (message.get('artifact') or {}).get('transcript') or ''
    return FarmerProfile(
        call_id=call_id,
        phone=text((call.get('customer') or {}).get('number')),
        farmer_name=text(data.get('farmer_name')),
        state=state(data.get('state')),
        county=text(data.get('county')),
        crops=crops(data.get('crops')),
        damage_type=damage_type(data.get('damage_type')),
        acres_damaged=number(data.get('acres_damaged')),
        total_acres=number(data.get('total_acres')),
        loss_percent=number(data.get('loss_percent')),
        loss_date=iso_date(data.get('loss_date')),
        annual_income=number(data.get('annual_income')),
        has_crop_insurance=yes_no(data.get('has_crop_insurance')),
        years_farming=number(data.get('years_farming')),
        is_organic=yes_no(data.get('is_organic')),
        story=f"{analysis.get('summary') or ''}\n{transcript}".strip(),
    )

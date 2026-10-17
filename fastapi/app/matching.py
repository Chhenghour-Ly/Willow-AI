"""Deep search + matching over program records.

Retrieval ranks programs by how well their text fits the farmer's story;
rules then decide met / blocked / unknown for every eligibility requirement.
Rules decide eligibility; text relevance only orders programs within a status.
"""
import math
import re
from dataclasses import asdict, dataclass
from datetime import date

from app.profile import FarmerProfile

CROP_GROUPS = {
    'fruit': {'apples', 'peaches', 'cherries', 'citrus', 'berries', 'grapes'},
    'vegetables': {'tomatoes', 'peppers'},
    'livestock': {'cattle', 'sheep', 'goats', 'hogs'},
    'orchard': {'apples', 'peaches', 'cherries', 'citrus', 'nuts'},
}
STOPWORDS = set('a an and are as at be by for from i in is it my of on or our so that the this to was we with you your'
                ' have has had do did about out up ai user hi how can help'.split())
STATUS_ORDER = {'likely': 0, 'possible': 1, 'not_eligible': 2}


@dataclass
class ProgramMatch:
    program_id: str
    name: str
    agency: str
    kind: str
    status: str
    score: float
    met: list[str]
    blocked: list[str]
    unknown: list[str]
    explanation: str
    amount: dict | None
    deadline: str | None
    required_documents: list[str]
    synthetic: bool

    def to_dict(self):
        return asdict(self)


def tokens(value):
    return {w for w in re.findall(r'[a-z]+', value.lower()) if w not in STOPWORDS and len(w) > 2}


def program_text(program):
    return f"{program['name']} {program['summary']} {program['description']}"


def money(value):
    return f'${value:,.0f}'


def check(value, ok, met, blocked, question):
    """One requirement -> ('met'|'blocked'|'unknown', reason)."""
    if value is None or value == []:
        return 'unknown', question
    return ('met', met) if ok(value) else ('blocked', blocked)


def evaluate(profile: FarmerProfile, rules: dict, deadline: str | None, today: date):
    results = []
    crops = set(profile.crops) | {group for group, members in CROP_GROUPS.items() if members & set(profile.crops)}
    if rules.get('states'):
        results.append(check(profile.state, lambda s: s in rules['states'], f'Available in {profile.state}',
                             f"Only for farms in {', '.join(rules['states'])}", 'Which state is the farm in?'))
    if rules.get('crops'):
        hit = sorted(crops & set(rules['crops']))
        results.append(check(profile.crops, lambda _: hit, f"Covers {', '.join(hit)}",
                             f"Only covers {', '.join(rules['crops'])}", 'What do you grow or raise?'))
    if rules.get('damage_types'):
        label = (profile.damage_type or '').replace('_', ' ')
        results.append(check(profile.damage_type, lambda d: d in rules['damage_types'], f'Covers {label} damage',
                             f"Only covers {', '.join(d.replace('_', ' ') for d in rules['damage_types'])} damage",
                             'What caused the damage?'))
    if rules.get('min_loss_percent') is not None:
        need = rules['min_loss_percent']
        results.append(check(profile.loss_percent, lambda p: p >= need,
                             f'Loss of {profile.loss_percent:g}% meets the {need}% minimum' if profile.loss_percent is not None else '',
                             f'Needs at least {need}% loss', 'About what percent of the crop was lost?'))
    if rules.get('max_income') is not None:
        cap = rules['max_income']
        results.append(check(profile.annual_income, lambda i: i <= cap, f'Income under the {money(cap)} limit',
                             f'Income over the {money(cap)} limit', 'What is your yearly farm income?'))
    if rules.get('max_acres') is not None:
        cap = rules['max_acres']
        results.append(check(profile.total_acres, lambda a: a <= cap, f'Farm size under {cap} acres',
                             f'Only for farms under {cap} acres', 'How many acres do you farm?'))
    if rules.get('requires_crop_insurance') is not None:
        want = rules['requires_crop_insurance']
        results.append(check(profile.has_crop_insurance, lambda h: h == want,
                             'You have crop insurance' if want else 'For crops without crop insurance',
                             'Requires a crop insurance policy' if want else 'Only for crops without crop insurance',
                             'Do you have crop insurance?'))
    if rules.get('max_years_farming') is not None:
        cap = rules['max_years_farming']
        results.append(check(profile.years_farming, lambda y: y <= cap, f'Farming {cap} years or less',
                             f'Only for farmers in their first {cap} years', 'How many years have you been farming?'))
    if rules.get('requires_organic'):
        results.append(check(profile.is_organic, bool, 'Certified organic', 'Only for certified organic farms',
                             'Is the farm certified organic?'))
    if deadline and date.fromisoformat(deadline) < today:
        results.append(('blocked', f'Deadline passed ({deadline})'))
    return results


def match_programs(profile: FarmerProfile, programs: list[dict], today: date) -> list[ProgramMatch]:
    query = tokens(f"{profile.story} {' '.join(profile.crops)} {profile.damage_type or ''}")
    docs = {p['id']: tokens(program_text(p)) for p in programs}
    idf = {w: math.log(1 + len(docs) / (1 + sum(w in d for d in docs.values()))) for w in query}
    matches = []
    for program in programs:
        results = evaluate(profile, program.get('eligibility') or {}, program.get('deadline'), today)
        grouped = {kind: [reason for k, reason in results if k == kind] for kind in ('met', 'blocked', 'unknown')}
        status = 'not_eligible' if grouped['blocked'] else 'possible' if grouped['unknown'] else 'likely'
        explanation = {
            'likely': 'Good fit: ' + ('; '.join(grouped['met']) or 'open to every farm') + '.',
            'possible': 'Could fit. Still need: ' + ' '.join(grouped['unknown']),
            'not_eligible': 'Not a fit: ' + '; '.join(grouped['blocked']) + '.',
        }[status]
        matches.append(ProgramMatch(
            program_id=program['id'], name=program['name'], agency=program['agency'], kind=program['kind'],
            status=status, score=round(sum(idf[w] for w in query & docs[program['id']]), 3),
            explanation=explanation, amount=program.get('amount'), deadline=program.get('deadline'),
            required_documents=program.get('required_documents', []), synthetic=program.get('synthetic', False),
            **grouped))
    return sorted(matches, key=lambda m: (STATUS_ORDER[m.status], -m.score, -((m.amount or {}).get('max') or 0)))

"""Retrieve official program text and check each requirement against the farmer profile.

Retrieval ranks the stored USDA passages by how well they fit the farmer's story and
returns them as cited evidence. Rules then sort every requirement into a reason (what
fits), an obstacle (a conflict with what the farmer said), or a missing requirement
(something nobody knows yet). Missing facts never count against the farmer, and
nothing here is an eligibility decision or a probability; the agency decides.
"""
import math
import re
from dataclasses import dataclass, field
from datetime import date

from app.profile import FarmerProfile

FIT_ORDER = {'potential_fit': 0, 'needs_information': 1, 'unlikely_fit': 2}
STOPWORDS = set('a an and are as at be by for from i in is it my of on or our so that the this to was we with you your'
                ' have has had do did about out up can will not'.split())
LABELS = {'irrigation_upgrade': 'irrigation upgrade', 'water_conservation': 'water conservation',
          'soil_health': 'soil health', 'long_term_conservation': 'long-term conservation',
          'financing': 'financing', 'equipment': 'equipment', 'expansion': 'expansion', 'crop_damage': 'crop damage'}


@dataclass
class Findings:
    program: dict
    reasons: list = field(default_factory=list)
    obstacles: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    conflict: bool = False  # an obstacle that contradicts something the farmer actually said

    def cite(self, bucket, text, source=None, conflict=False):
        url = self.program['sources'][source]['url'] if source is not None else None
        getattr(self, bucket).append({'text': text, 'source_url': url})
        self.conflict = self.conflict or conflict


def tokens(value):
    return {w for w in re.findall(r'[a-z]+', value.lower()) if w not in STOPWORDS and len(w) > 2}


def money(value):
    return f'${value:,.0f}'


def labels(needs):
    return ', '.join(LABELS.get(n, n) for n in needs)


def retrieve(profile: FarmerProfile, programs: list[dict], k: int = 3) -> dict[str, list[dict]]:
    """Top-k passages per program, scored by inverse-document-frequency overlap with the farmer's story."""
    query = tokens(profile.search_text())
    passages = [(p, passage) for p in programs for passage in p['passages']]
    idf = {w: math.log(1 + len(passages) / (1 + sum(w in tokens(x['text']) for _, x in passages))) for w in query}
    ranked = {}
    for program in programs:
        scored = sorted(((sum(idf[w] for w in query & tokens(x['text'])), x) for x in program['passages']),
                        key=lambda s: -s[0])
        ranked[program['id']] = [{'text': x['text'], 'source_url': program['sources'][x['source']]['url'],
                                  'relevance': round(score, 3)} for score, x in scored[:k]]
    return ranked


def check_eqip(p: FarmerProfile, f: Findings):
    aligned = [n for n in p.needs if n in f.program['serves_needs']]
    if aligned:
        f.cite('reasons', f'Your project ({labels(aligned)}) is the kind of conservation work EQIP helps pay for.', 0)
    elif p.needs:
        f.cite('obstacles', f'EQIP pays for conservation practices; your stated needs ({labels(p.needs)}) are not conservation work.', 0, conflict=True)
    else:
        f.cite('missing', 'What do you want to improve on the farm (for example irrigation, water use or soil health)?')

    if p.funding_preference in ('nonrepayable_only', 'prefer_nonrepayable_open_to_loan'):
        f.cite('reasons', 'EQIP payments do not have to be repaid, which matches your preference.', 0)

    if p.land_control == 'owned':
        f.cite('reasons', 'You own the land, so you can show control of it for the contract term.', 1)
    elif p.land_control == 'leased':
        f.cite('reasons', 'Renters can apply when the lease covers the contract term.', 1)
        f.cite('missing', 'A lease covering the full EQIP contract term, and the landowner’s permission for structural practices such as irrigation.', 1)
    elif p.land_control == 'other':
        f.cite('missing', 'Proof you control the land for the contract term (lease, deed or other agreement).', 1)
    else:
        f.cite('missing', 'Do you own or lease the land, and for how long?', 1)

    if p.project_status == 'not_started':
        f.cite('reasons', 'You have not started the work, which matters: EQIP does not pay for practices begun before the contract is approved.', 0)
    elif p.project_status in ('in_progress', 'completed'):
        f.cite('obstacles', 'Work already started is generally not eligible unless NRCS approved a waiver before it began.', 0, conflict=True)
    else:
        f.cite('missing', 'Have you started the project yet? EQIP does not pay for work begun before the contract is approved.', 0)

    if {'irrigation_upgrade', 'water_conservation'} & set(p.needs):
        if p.irrigated_years_of_last_5 is None:
            f.cite('missing', 'Was the land irrigated in at least 2 of the last 5 years? (required for water-saving irrigation practices)', 1)
        elif p.irrigated_years_of_last_5 >= 2:
            f.cite('reasons', f'The land was irrigated {p.irrigated_years_of_last_5} of the last 5 years, meeting the 2-of-5 irrigation history rule.', 1)
        else:
            f.cite('obstacles', 'Irrigation practices need land irrigated in at least 2 of the last 5 years; ask NRCS about the drought exception or a waiver.', 1)

    f.cite('missing', 'Average adjusted gross income of $900,000 or less (form CCC-941).', 1)
    f.cite('missing', 'Highly erodible land and wetland conservation compliance (form AD-1026) and farm records with FSA.', 1)


def check_microloan(p: FarmerProfile, f: Findings):
    if p.funding_preference == 'nonrepayable_only':
        f.cite('obstacles', 'This is a loan you repay, and you said you only want help you do not have to repay.', conflict=True)
    elif p.funding_preference == 'prefer_nonrepayable_open_to_loan':
        f.cite('reasons', 'A loan is not your first choice, but you said you would consider one, so this is a backup option.')
    elif p.funding_preference == 'loan_ok':
        f.cite('reasons', 'You said a loan is fine.')
    else:
        f.cite('missing', 'Would you consider a loan you have to repay?')

    uses = [n for n in p.needs if n in f.program['serves_needs']]
    if uses:
        f.cite('reasons', f'Operating microloans can be used for {labels(uses)}.', 1)
    elif not p.needs:
        f.cite('missing', 'What would the money be used for?', 1)

    cap = f.program['max_amount_usd']
    if p.assistance_needed_usd is None:
        f.cite('missing', 'How much money do you need?', 0)
    elif p.assistance_needed_usd <= cap:
        f.cite('reasons', f'The {money(p.assistance_needed_usd)} you need is within the {money(cap)} microloan limit.', 0)
    else:
        f.cite('obstacles', f'You need {money(p.assistance_needed_usd)}, above the {money(cap)} microloan limit.', 0, conflict=True)

    f.cite('missing', 'Satisfactory credit history, and unable to get credit elsewhere at reasonable rates and terms.', 0)
    f.cite('missing', 'U.S. citizen, non-citizen national or qualified alien, with farm management experience or education.', 0)
    f.cite('missing', 'Collateral worth at least the loan amount. FSA reviews ability to repay; Willow does not assess it.', 0)


CHECKS = {'eqip': check_eqip, 'fsa-operating-microloan': check_microloan}


def match_programs(profile: FarmerProfile, programs: list[dict], today: date) -> list[dict]:
    evidence = retrieve(profile, programs)
    core_missing = profile.missing_core()
    results = []
    for program in programs:
        if program['id'] not in CHECKS:
            continue
        f = Findings(program)
        if 'state' in core_missing:
            f.cite('missing', 'Which state and county is the farm in?')
        CHECKS[program['id']](profile, f)
        fit = 'unlikely_fit' if f.conflict else 'needs_information' if core_missing else 'potential_fit'
        deadline = (program.get('deadlines') or {}).get(profile.state or '')
        if deadline and date.fromisoformat(deadline['date']) < today:
            deadline = None  # past cutoffs roll to the next ranking period; don't show a stale date
        results.append({
            'program_id': program['id'],
            'program_name': program['name'],
            'agency': program['agency'],
            'description': program.get('description'),
            'repayable': program['repayable'],
            'fit_status': fit,
            'reasons': f.reasons,
            'obstacles': f.obstacles,
            'missing_requirements': f.missing,
            'application_deadline': {'date': deadline['date'], 'note': deadline['note'],
                                     'source_url': program['sources'][deadline['source']]['url']} if deadline else None,
            'official_source_urls': program['sources'],
            'evidence': evidence[program['id']],
            'next_action': program['next_action'].format(county=profile.county or 'your county'),
            # Relevance of the retrieved text only. Not an eligibility probability.
            'relevance': round(sum(e['relevance'] for e in evidence[program['id']]), 3),
        })

    prefers_grants = profile.funding_preference in ('nonrepayable_only', 'prefer_nonrepayable_open_to_loan')
    return sorted(results, key=lambda m: (FIT_ORDER[m['fit_status']], prefers_grants and m['repayable'],
                                          -len(m['reasons']), -m['relevance']))

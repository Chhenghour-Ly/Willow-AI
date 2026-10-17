from app.schemas import FACT_NAMES, Fact, RagInput


def normalize_demo(payload):
    # This is our fictional fixture contract, deliberately not a live Vapi parser.
    if payload.get('fictional_demo') is not True:
        raise ValueError('Only the fictional demo fixture is supported until a real event is inspected')
    call_id = payload['message']['call']['id']
    if not isinstance(call_id, str) or not 1 <= len(call_id) <= 200:
        raise ValueError('Invalid call ID')
    raw = payload['demo_facts']
    if not isinstance(raw, dict) or set(raw) - set(FACT_NAMES):
        raise ValueError('Invalid demo facts')
    facts = {}
    for name in FACT_NAMES:
        value = raw.get(name)
        fact = Fact(value=value, confirmed=False,
                    sources=[f'call:{call_id}#/demo_facts/{name}'] if value is not None else [])
        facts[name] = fact.model_dump()
    return call_id, facts


def missing(facts):
    return [key for key, fact in facts.items() if fact['value'] is None or not fact['value'].strip()]


def rag_input(facts, documents):
    return RagInput(facts=facts, crop=facts['crop']['value'], location=facts['location']['value'],
                    policy_identifiers=[facts['policy_number']['value']] if facts['policy_number']['value'] else [],
                    document_references=documents,
                    missing_or_uncertain=[key for key, fact in facts.items()
                                          if fact['value'] is None or not fact['confirmed']])


def draft_notice(facts):
    """Replace this deterministic drafting function when the team connects a model."""
    lines = ['DRAFT DAMAGE NOTICE — farmer-reported information, not verified evidence.',
             'Please record this report of crop damage and advise on next steps.']
    for key in FACT_NAMES:
        fact = facts[key]
        value = fact['value'] if fact['value'] is not None else '[unknown]'
        label = 'farmer confirmed' if fact['confirmed'] else 'unconfirmed'
        lines.append(f"{key.replace('_', ' ').capitalize()}: {value} ({label})")
    lines.append('This notice reports damage; it is not a completed payout claim.')
    return '\n'.join(lines)


def tasks_for(facts, attachments):
    tasks = [{'kind': 'contact_agent', 'urgent': True,
              'text': 'Contact your insurance agent promptly to confirm notice requirements and timing; do not wait for documents.'}]
    tasks += [{'kind': 'missing_fact', 'field': field, 'text': f'Provide {field.replace("_", " ")}.'}
              for field in missing(facts)]
    tasks += [{'kind': 'confirm_fact', 'field': field, 'text': f'Review {field.replace("_", " ")}.'}
              for field, fact in facts.items() if fact['value'] is not None and not fact['confirmed']]
    if not attachments:
        tasks.append({'kind': 'documents', 'text': 'Gather policy documents and damage evidence if available.'})
    tasks.append({'kind': 'requirements', 'text': 'Confirm applicable requirements with the agent. No deadline has been calculated.'})
    return tasks

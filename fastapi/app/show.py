"""Inspect saved calls from the terminal.

    python -m app.show                    list saved calls
    python -m app.show CALL_ID            structured output, profile, matches with citations
    python -m app.show CALL_ID --rematch  re-run the pipeline on the saved payload
"""
import argparse
import json

from sqlalchemy import select

from app.config import Settings
from app.db import Call, Database
from app.main import process_call
from app.profile import structured_data


def main():
    parser = argparse.ArgumentParser(description='Show saved Willow calls')
    parser.add_argument('call_id', nargs='?')
    parser.add_argument('--rematch', action='store_true', help='re-run profile + matching with the current code')
    args = parser.parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_url)

    if not args.call_id:
        with database.transaction() as db:
            for call in db.scalars(select(Call).order_by(Call.created_at)):
                print(f"{call.call_id}  {call.status:<17} {(call.profile or {}).get('farmer_name') or '-'}")
        return
    if args.rematch:
        with database.transaction() as db:
            if not db.get(Call, args.call_id):
                raise SystemExit(f'No saved call {args.call_id}')
            db.get(Call, args.call_id).status = 'received'
        process_call(database, settings, args.call_id)

    with database.transaction() as db:
        call = db.get(Call, args.call_id)
        if not call:
            raise SystemExit(f'No saved call {args.call_id}')
        print('status:', call.status, call.error or '')
        print('\n== Structured output from Vapi ==')
        print(json.dumps(structured_data(call.payload['message']), indent=2))
        print('\n== Normalized profile ==')
        print(json.dumps(call.profile, indent=2))
        for m in call.matches:
            print(f"\n== {m['program_name']}: {m['fit_status']} ==")
            for bucket in ('reasons', 'obstacles', 'missing_requirements'):
                for item in m[bucket]:
                    print(f"  {bucket[:7]:<8} {item['text']}" + (f"\n{'':11}source: {item['source_url']}" if item['source_url'] else ''))
            if m['application_deadline']:
                print('  deadline', m['application_deadline']['date'], '-', m['application_deadline']['note'])
            print('  next    ', m['next_action'])


if __name__ == '__main__':
    main()

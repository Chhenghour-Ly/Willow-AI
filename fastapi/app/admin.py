"""Trusted local operator tools, never exposed over HTTP."""
import argparse
import hashlib
import re
from pathlib import Path

from sqlalchemy import select, func

from app.config import Settings
from app.db import Activity, CallBinding, Case, Database, Document, Farmer, Job, Notification, Submission
from app.security import issue_review_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('seed-demo', help='Seed a fictional verified farmer and call binding (demo only)')
    bind = commands.add_parser('bind-call', help='Only after independent identity and destination verification')
    bind.add_argument('call_id')
    bind.add_argument('farmer_id')
    bind.add_argument('--phone', required=True)
    bind.add_argument('--identity-and-phone-verified', action='store_true', required=True)
    bind.add_argument('--sms-consent', action='store_true')
    token = commands.add_parser('review-token', help='Issue a demo credential directly to the operator terminal; never redirect to logs')
    token.add_argument('case_id')
    document = commands.add_parser('add-document', help='Store immutable private bytes for a verified case')
    document.add_argument('case_id')
    document.add_argument('document_id')
    document.add_argument('path')
    reconcile = commands.add_parser('reconcile', help='Record a provider-verified result; never queues another send')
    reconcile.add_argument('kind', choices=['submit', 'notify'])
    reconcile.add_argument('case_id')
    reconcile.add_argument('outcome', choices=['sent', 'failed'])
    reconcile.add_argument('--provider-id', required=True)
    reconcile.add_argument('--checked-provider', action='store_true', required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_url)
    with database.transaction() as db:
        if args.command == 'seed-demo':
            if not settings.demo_mode:
                parser.error('Demo seed requires DEMO_MODE=true')
            if not db.get(Farmer, 'farmer-demo'):
                db.add(Farmer(id='farmer-demo', phone='+12025550101', verified=True, sms_consent=True))
            if not db.get(CallBinding, 'fictional-call-001'):
                db.add(CallBinding(call_id='fictional-call-001', farmer_id='farmer-demo'))
        elif args.command == 'bind-call':
            if not re.fullmatch(r'\+[1-9][0-9]{7,14}', args.phone):
                parser.error('Phone must be E.164')
            if db.get(CallBinding, args.call_id):
                parser.error('Call binding already exists and cannot be reassigned')
            farmer = db.get(Farmer, args.farmer_id)
            if farmer and farmer.phone != args.phone:
                parser.error('Existing verified account has a different phone')
            if not farmer:
                farmer = Farmer(id=args.farmer_id, phone=args.phone, verified=True, sms_consent=args.sms_consent)
                db.add(farmer)
            db.add(CallBinding(call_id=args.call_id, farmer_id=args.farmer_id))
        else:
            case = db.get(Case, args.case_id)
            if not case:
                parser.error('Unknown case')
            if args.command == 'review-token':
                if not settings.demo_mode or settings.sms_provider != 'mock':
                    parser.error('Manual demo token requires demo mode and mock SMS')
                credential = issue_review_token(db, case.id, settings)
                db.add(Activity(case_id=case.id, kind='demo_review_token_issued'))
            elif args.command == 'add-document':
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', args.document_id):
                    parser.error('Document ID must be URL-safe')
                path = Path(args.path)
                if path.stat().st_size > 5_000_000:
                    parser.error('Document limit is 5 MB')
                content = path.read_bytes()
                name = path.name
                if any(ord(c) < 32 for c in name):
                    parser.error('Invalid filename')
                version = (db.scalar(select(func.max(Document.version)).where(
                    Document.case_id == case.id, Document.document_id == args.document_id)) or 0)+1
                db.add(Document(case_id=case.id, document_id=args.document_id, version=version,
                                name=name, sha256=hashlib.sha256(content).hexdigest(), content=content))
                db.add(Activity(case_id=case.id, kind='document_added', detail={'document_id': args.document_id, 'version': version}))
                print(f'Document version: {version}; attach it through PATCH before approval.')
            else:
                model = Submission if args.kind == 'submit' else Notification
                attempt = db.scalar(select(model).where(model.case_id == case.id))
                if not attempt or attempt.status != 'uncertain':
                    parser.error('Only uncertain deliveries require this reconciliation')
                attempt.status = args.outcome
                attempt.provider_id = args.provider_id
                attempt.error = None if args.outcome == 'sent' else 'provider_confirmed_not_accepted'
                job = db.scalar(select(Job).where(Job.key == f'{args.kind}:{case.id}'))
                job.status = 'done' if args.outcome == 'sent' else 'failed'
                db.add(Activity(case_id=case.id, kind='delivery_reconciled', detail={'kind': args.kind, 'outcome': args.outcome}))
    if args.command == 'review-token':
        # Direct credential issuance is not an application log; never persist plaintext tokens.
        print(f'{settings.review_base_url}#token={credential}')


if __name__ == '__main__':
    main()

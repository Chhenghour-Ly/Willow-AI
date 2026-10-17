import argparse
import hashlib
import time

from sqlalchemy import select

from app.adapters import DeliveryResult, retrieve_requirements, send_email, send_sms
from app.config import Settings
from app.db import Activity, Approval, Case, Database, Document, Farmer, Job, Notification, Report, Submission
from app.reports import draft_notice, missing, rag_input, tasks_for
from app.security import issue_review_token


def recover_expired(db):
    for job in db.scalars(select(Job).where(Job.status == 'running', Job.lease_until <= time.time())):
        if job.kind == 'process':
            job.status = 'queued' if job.attempts < 3 else 'failed'
            if job.status == 'failed':
                db.get(Case, job.case_id).processing_status = 'failed'
        else:
            model = Submission if job.kind == 'submit' else Notification
            attempt = db.scalar(select(model).where(model.case_id == job.case_id))
            if attempt:
                attempt.status = 'uncertain'
                attempt.error = 'worker_interrupted_reconcile_before_resend'
            job.status = 'uncertain'
        db.add(Activity(case_id=job.case_id, kind='expired_job_recovered', detail={'status': job.status}))


def finish(db, job_id, result):
    job = db.get(Job, job_id)
    if job.status != 'running':
        db.add(Activity(case_id=job.case_id, kind='late_provider_result',
                        detail={'status': result.status, 'provider_id': result.provider_id}))
        return
    model = Submission if job.kind == 'submit' else Notification
    attempt = db.scalar(select(model).where(model.case_id == job.case_id))
    attempt.status = result.status
    if result.provider_id is not None:
        attempt.provider_id = result.provider_id
    attempt.error = result.error
    attempt.simulated = result.simulated
    job.status = 'done' if result.status == 'sent' else result.status
    job.error = result.error
    db.add(Activity(case_id=job.case_id, kind=f'{job.kind}_{result.status}',
                    detail={'simulated': result.simulated, 'provider_id': result.provider_id}))


def run_once(database: Database, settings: Settings) -> bool:
    with database.transaction() as db:
        recover_expired(db)
        job = db.scalar(select(Job).where(Job.status == 'queued', Job.available_at <= time.time())
                        .order_by(Job.available_at, Job.id).limit(1))
        if not job:
            return False
        job.status = 'running'
        job.attempts += 1
        job.lease_until = time.time()+settings.job_lease_seconds
        job_id, kind, case_id = job.id, job.kind, job.case_id
        claimed_attempt = job.attempts

    try:
        if kind == 'process':
            with database.read() as db:
                facts = db.get(Case, case_id).facts
            rag = retrieve_requirements(rag_input(facts, []))
            body = {'facts': facts, 'missing_information': missing(facts),
                    'requirements': [item.model_dump() for item in rag.requirements],
                    'unresolved_questions': rag.unresolved_questions, 'rag_simulated': rag.simulated,
                    'draft_notice': draft_notice(facts), 'recipient': settings.default_recipient or None,
                    'attachments': [], 'tasks': tasks_for(facts, [])}
            with database.transaction() as db:
                job = db.get(Job, job_id)
                if job.status != 'running' or job.attempts != claimed_attempt:
                    return True
                case = db.get(Case, case_id)
                if case.draft_version == 0:
                    db.add(Report(case_id=case_id, version=1, body=body))
                    case.draft_version = 1
                    case.processing_status = 'ready'
                    db.add(Notification(case_id=case_id))
                    db.add(Job(key=f'notify:{case_id}', kind='notify', case_id=case_id))
                    db.add(Activity(case_id=case_id, kind='report_ready'))
                job.status = 'done'
            return True

        if kind == 'notify':
            with database.transaction() as db:
                job = db.get(Job, job_id)
                if job.status != 'running' or job.attempts != claimed_attempt:
                    return True
                if job.lease_until <= time.time():
                    recover_expired(db)
                    return True
                case = db.get(Case, case_id)
                farmer = db.get(Farmer, case.farmer_id)
                if case.processing_status != 'ready' or not farmer or not farmer.verified or not farmer.sms_consent:
                    finish(db, job_id, DeliveryResult('failed', error='verified_destination_and_consent_required'))
                    return True
                token = issue_review_token(db, case_id, settings)
                phone = farmer.phone
                db.scalar(select(Notification).where(Notification.case_id == case_id)).status = 'sending'
                db.add(Activity(case_id=case_id, kind='notify_dispatch_started'))
            # Fragment keeps the token out of HTTP access logs and referrer headers.
            result = send_sms(phone, f'{settings.review_base_url}#token={token}', settings)
        elif kind == 'submit':
            with database.transaction() as db:
                job = db.get(Job, job_id)
                if job.status != 'running' or job.attempts != claimed_attempt:
                    return True
                if job.lease_until <= time.time():
                    recover_expired(db)
                    return True
                submission = db.scalar(select(Submission).where(Submission.case_id == case_id))
                approval = db.get(Approval, submission.approval_id)
                snapshot = approval.snapshot
                documents = []
                for ref in snapshot['attachments']:
                    document = db.scalar(select(Document).where(Document.case_id == case_id,
                                         Document.document_id == ref['document_id'], Document.version == ref['version']))
                    if not document or hashlib.sha256(document.content).hexdigest() != ref['sha256']:
                        finish(db, job_id, DeliveryResult('failed', error='approved_attachment_unavailable'))
                        return True
                    documents.append({'name': ref['name'], 'content': document.content})
                submission.status = 'sending'
                submission_id = submission.id
                if settings.email_provider == 'smtp':
                    submission.provider_id = f'<{submission_id}@damage-notice.invalid>'
                db.add(Activity(case_id=case_id, kind='submit_dispatch_started'))
            result = send_email(snapshot, documents, settings, submission_id)
        else:
            raise ValueError('Unknown job kind')
        with database.transaction() as db:
            finish(db, job_id, result)
    except Exception as exc:
        # Never persist raw exception text: SDK errors can contain credentials or personal data.
        with database.transaction() as db:
            job = db.get(Job, job_id)
            if job.status != 'running' or job.attempts != claimed_attempt:
                return True
            if kind == 'process':
                retryable = isinstance(exc, (TimeoutError, ConnectionError))
                job.status = 'queued' if retryable and job.attempts < 3 else 'failed'
                job.available_at = time.time()+2**job.attempts
                job.error = 'report_processing_failed'
                if job.status == 'failed':
                    db.get(Case, case_id).processing_status = 'failed'
                db.add(Activity(case_id=case_id, kind='report_processing_failed', detail={'attempt': job.attempts}))
            else:
                finish(db, job_id, DeliveryResult('uncertain', error='unexpected_delivery_failure_requires_reconciliation'))
    return True


def main():
    parser = argparse.ArgumentParser(description='Durable damage-notice worker')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_url)
    if args.once:
        run_once(database, settings)
        return
    try:
        while True:
            if not run_once(database, settings):
                time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

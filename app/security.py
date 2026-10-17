import hashlib
import secrets
import time

from sqlalchemy import select

from app.db import ReviewToken


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def issue_review_token(db, case_id, settings):
    for old in db.scalars(select(ReviewToken).where(ReviewToken.case_id == case_id, ReviewToken.used == False)):
        old.used = True
    token = secrets.token_urlsafe(32)
    db.add(ReviewToken(token_hash=digest(token), case_id=case_id, expires_at=time.time()+settings.review_ttl))
    return token

"""Pure contract/adapter checks also runnable with unittest and Pydantic only."""
import json
import smtplib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app.adapters import allowed_recipient, retrieve_requirements, send_email, send_sms
from app.config import Settings
from app.reports import draft_notice, missing, normalize_demo, rag_input, tasks_for
from app.schemas import CasePatch


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(Path('fixtures/fictional-call.json').read_text())
        self.call_id, self.facts = normalize_demo(self.payload)
        self.settings = Settings()
        self.snapshot = {'recipient': 'damage-demo@example.test', 'draft_notice': 'Exact approved text', 'attachments': []}

    def test_unknowns_and_unconfirmed_values(self):
        self.assertIsNone(self.facts['policy_number']['value'])
        self.assertIn('policy_number', missing(self.facts))
        self.assertFalse(self.facts['crop']['confirmed'])
        self.assertIn('call:fictional-call-001', self.facts['crop']['sources'][0])

    def test_no_guessed_deadlines_or_claim_completion(self):
        draft = draft_notice(self.facts)
        self.assertIn('[unknown]', draft)
        self.assertNotIn('72', draft)
        self.assertIn('not a completed payout claim', draft)
        self.assertIn('Farmer reports wind damage', draft)

    def test_contact_agent_task_survives_missing_documents(self):
        tasks = tasks_for(self.facts, [])
        self.assertEqual(tasks[0]['kind'], 'contact_agent')
        self.assertTrue(tasks[0]['urgent'])
        self.assertTrue(any(task['kind'] == 'documents' for task in tasks))

    def test_reject_live_payload_and_invented_facts(self):
        self.payload.pop('fictional_demo')
        with self.assertRaises(ValueError):
            normalize_demo(self.payload)
        with self.assertRaises(ValidationError):
            CasePatch(version=1, facts={'invented_field': {'value': 'x'}})

    def test_reject_noneditable_fields(self):
        with self.assertRaises(ValidationError):
            CasePatch(version=1, farmer_id='attacker')

    def test_rag_contract_is_labeled_and_sources_preserved(self):
        result = retrieve_requirements(rag_input(self.facts, []))
        self.assertTrue(result.simulated)
        self.assertEqual(result.requirements[0].applicability, 'unknown')
        self.assertFalse(result.requirements[0].reviewed)
        self.assertTrue(result.requirements[0].sources)

    def test_allowlist_checks_every_provider_mode(self):
        for demo in (True, False):
            self.settings.demo_mode = demo
            for recipient in ('attacker@example.net', 'damage-demo@example.test.evil.com',
                              'damage-demo@example.test\r\nBcc:attacker@example.net',
                              'damage-demo@example.test,attacker@example.net'):
                self.assertFalse(allowed_recipient(recipient, self.settings))
                self.snapshot['recipient'] = recipient
                self.assertEqual(send_email(self.snapshot, [], self.settings, 'id').status, 'failed')

    def test_simulated_delivery_is_explicit(self):
        self.assertTrue(send_email(self.snapshot, [], self.settings, 'id').simulated)
        self.assertTrue(send_sms('+12025550101', 'https://example.test/#token=x', self.settings).simulated)

    def test_real_sms_requires_explicit_switch(self):
        self.settings.sms_provider = 'twilio'
        self.assertEqual(send_sms('+12025550101', 'https://example.test', self.settings).status, 'failed')

    def smtp_settings(self):
        self.settings.email_provider = 'smtp'
        self.settings.smtp_host = 'smtp.example.test'
        self.settings.smtp_from = 'sender@example.test'

    def test_smtp_lost_response_is_uncertain(self):
        self.smtp_settings()
        smtp = Mock()
        smtp.send_message.side_effect = TimeoutError()
        with patch('app.adapters.smtplib.SMTP', return_value=smtp):
            result = send_email(self.snapshot, [], self.settings, 'id')
        self.assertEqual(result.status, 'uncertain')

    def test_smtp_pre_dispatch_failure_is_failed(self):
        self.smtp_settings()
        with patch('app.adapters.smtplib.SMTP', side_effect=ConnectionRefusedError()):
            self.assertEqual(send_email(self.snapshot, [], self.settings, 'id').status, 'failed')

    def test_smtp_rejection_is_failed(self):
        self.smtp_settings()
        smtp = Mock()
        smtp.send_message.side_effect = smtplib.SMTPDataError(550, b'rejected')
        with patch('app.adapters.smtplib.SMTP', return_value=smtp):
            self.assertEqual(send_email(self.snapshot, [], self.settings, 'id').status, 'failed')

    def test_smtp_accepted_notice_survives_quit_failure(self):
        self.smtp_settings()
        smtp = Mock()
        smtp.send_message.return_value = {}
        smtp.quit.side_effect = smtplib.SMTPResponseException(500, b'quit failed')
        with patch('app.adapters.smtplib.SMTP', return_value=smtp):
            result = send_email(self.snapshot, [{'name': 'evidence.txt', 'content': b'approved evidence'}], self.settings, 'id')
        self.assertEqual(result.status, 'sent')
        sent = smtp.send_message.call_args.args[0]
        self.assertEqual(sent['To'], self.snapshot['recipient'])
        self.assertEqual(sent.get_body().get_content().strip(), 'Exact approved text')
        self.assertEqual(next(sent.iter_attachments()).get_payload(decode=True), b'approved evidence')
        self.assertEqual(result.provider_id, '<id@damage-notice.invalid>')


if __name__ == '__main__':
    unittest.main()

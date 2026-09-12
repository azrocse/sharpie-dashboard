import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from opportunities import CDMX
from publish_opportunities import confirm_and_archive


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'data/opportunities.json'
        self.path.parent.mkdir()
        self.path.write_text('{"schemaVersion":1,"picks":[],"count":0}')
        kickoff = datetime.now(CDMX) + timedelta(hours=2)
        self.pick = {'date': kickoff.date().isoformat(), 'iso': kickoff.isoformat(),
                     'game': 'A vs B', 'pick': 'A', 'market': 'Moneyline',
                     'actionKey': 'bet', 'pickCategory': 'FREE', 'stake': 1.5,
                     'marketSignal': 'SMART_MONEY', 'status': 'UPCOMING'}
        self.raw = json.dumps([self.pick]).encode()
        self.html = b'<script>window.SHARPIE_PICKS=' + self.raw + b';</script>'

    def git(self, *args):
        if args[0] == 'rev-parse':
            return b'abc123\n'
        return self.html if args[-1].endswith(':index.html') else self.raw

    def response(self, content):
        return Mock(content=content)

    def run_confirmation(self, responses):
        with patch('publish_opportunities.git', side_effect=self.git), patch(
                'publish_opportunities.requests.get', side_effect=responses):
            return confirm_and_archive(root=self.root, url='https://example.test/', attempts=1)

    def test_old_deployment_does_not_change_archive_or_viewer(self):
        before = self.path.read_bytes()
        with self.assertRaises(RuntimeError):
            self.run_confirmation([self.response(b'old dashboard')])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.root / 'opportunities.html').exists())

    def test_mixed_deployment_does_not_archive(self):
        before = self.path.read_bytes()
        with self.assertRaises(RuntimeError):
            self.run_confirmation([self.response(self.html), self.response(b'[]')])
        self.assertEqual(self.path.read_bytes(), before)

    def test_archives_committed_and_served_picks_not_local_work(self):
        (self.root / 'picks.json').write_text('[]')
        result = self.run_confirmation([self.response(self.html), self.response(self.raw)])
        self.assertEqual(result['count'], 1)
        saved = result['picks'][0]
        self.assertEqual(saved['pick'], 'A')
        self.assertEqual(saved['publicationCommit'], 'abc123')
        self.assertEqual(saved['publicationStatus'], 'VERIFIED_PUBLIC')
        self.assertTrue(saved['publicationVerifiedAt'])

    def test_inconsistent_committed_files_are_rejected_before_http(self):
        self.html = b'<script>window.SHARPIE_PICKS=[];</script>'
        with self.assertRaises(ValueError):
            self.run_confirmation([])

    def test_public_event_already_started_is_not_new_opportunity(self):
        self.pick['iso'] = (datetime.now(CDMX) - timedelta(minutes=1)).isoformat()
        self.raw = json.dumps([self.pick]).encode()
        self.html = b'<script>window.SHARPIE_PICKS=' + self.raw + b';</script>'
        result = self.run_confirmation([self.response(self.html), self.response(self.raw)])
        self.assertEqual(result['count'], 0)

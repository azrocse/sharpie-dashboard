import json
from pathlib import Path
import tempfile
import unittest

from dashboard.generate_opportunities_viewer import generate_opportunities_viewer


class OpportunitiesViewerTests(unittest.TestCase):
    def test_render_preserves_saved_data_and_escapes_script_closing_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "opportunities.json"
            payload = {"schemaVersion": 1, "picks": [{"opportunityId": "example", "game": "</script><script>alert(1)</script>", "stake": 1.5, "ev": 4.23}]}
            source.write_text(json.dumps(payload), encoding="utf-8")
            before = source.read_bytes()
            output = generate_opportunities_viewer(source, root)
            html = output.read_text(encoding="utf-8")
            self.assertEqual(source.read_bytes(), before)
            self.assertIn('<\\/script><script>alert(1)<\\/script>', html)
            self.assertNotIn('__VIEWER_JS__', html)
            self.assertIn('id="filters"', html)
            self.assertIn('href="index.html"', html)
            self.assertIn('id="modelChart"', html)
            self.assertIn('id="signalsChart"', html)
            self.assertNotIn('id="status"', html)
            self.assertNotIn('id="access"', html)
            self.assertIn('id="evMin"', html)
            self.assertIn('aria-label="Buscar equipo"', html)
            self.assertIn('placeholder="Buscar equipo…"', html)
            self.assertIn('teamSearchText(p).includes(query)', html)
            self.assertNotIn('[p.game,p.pick,p.market,p.league,p.opportunityId]', html)
            self.assertIn("VALUE:'FREE'", html)
            self.assertIn('Últimos 5 movimientos', html)
            self.assertIn('Cambios del pick', html)
            self.assertIn('Ya no apostar', html)

    def test_empty_archive_has_a_viewer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "opportunities.json"
            source.write_text(json.dumps({"schemaVersion": 1, "picks": []}), encoding="utf-8")
            self.assertTrue(generate_opportunities_viewer(source, root).exists())

    def test_invalid_archive_does_not_replace_existing_viewer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "opportunities.json"
            source.write_text('{"schemaVersion":1,"picks":{}}', encoding="utf-8")
            output = root / "opportunities.html"
            output.write_text("previous viewer", encoding="utf-8")
            with self.assertRaises(ValueError):
                generate_opportunities_viewer(source, root)
            self.assertEqual(output.read_text(), "previous viewer")

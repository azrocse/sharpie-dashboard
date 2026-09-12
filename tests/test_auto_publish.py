"""Verifica el script con Git y Python simulados, sin publicar."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Script de actualización para Windows")
class AutoPublishTests(unittest.TestCase):
    def run_script(self, case):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(Path(__file__).resolve().parents[1] / "auto_publish.ps1", root / "auto_publish.ps1")
            harness = r'''
$global:LASTEXITCODE = 0
function global:python {
    Add-Content -LiteralPath (Join-Path $env:SHARPIE_TEST_ROOT 'calls.txt') -Value ('python ' + ($args -join ' '))
    $global:LASTEXITCODE = if ($env:SHARPIE_TEST_CASE -eq 'python_failure' -or ($env:SHARPIE_TEST_CASE -eq 'verification_failure' -and $args -contains 'src/publish_opportunities.py')) { 7 } else { 0 }
}
function global:git {
    Add-Content -LiteralPath (Join-Path $env:SHARPIE_TEST_ROOT 'calls.txt') -Value ('git ' + ($args -join ' '))
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'status' -and $env:SHARPIE_TEST_CASE -eq 'source_changes') { ' M src/main.py' }
    if ($args[0] -eq 'diff') { $global:LASTEXITCODE = 1 }
    if ($args[0] -eq 'push' -and $env:SHARPIE_TEST_CASE -eq 'push_failure') { $global:LASTEXITCODE = 9 }
}
& (Join-Path $env:SHARPIE_TEST_ROOT 'auto_publish.ps1')
exit $LASTEXITCODE
'''
            env = {**os.environ, "SHARPIE_TEST_ROOT": str(root), "SHARPIE_TEST_CASE": case}
            result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", harness], env=env, capture_output=True, timeout=30)
            calls = (root / "calls.txt").read_text(encoding="utf-8-sig")
            log = (root / "refresh_log.txt").read_text(encoding="utf-8-sig")
            return result.returncode, calls, log

    def test_pending_source_changes_block_automatic_publication(self):
        code, calls, log = self.run_script("source_changes")
        self.assertEqual(code, 0)
        self.assertNotIn("git push", calls)
        self.assertIn("python", calls)
        self.assertNotIn("git add", calls)
        self.assertNotIn("git commit", calls)
        self.assertIn("Dashboard actualizado localmente", log)
        self.assertIn("pendientes", log)

    def test_python_failure_stops_git_writes(self):
        code, calls, log = self.run_script("python_failure")
        self.assertNotEqual(code, 0)
        self.assertNotIn("git add", calls)
        self.assertIn("ERROR:", log)

    def test_failed_push_is_not_reported_as_success(self):
        code, calls, log = self.run_script("push_failure")
        self.assertNotEqual(code, 0)
        self.assertIn("git push", calls)
        self.assertNotIn("publicado correctamente", log)
        self.assertIn("ERROR:", log)
        self.assertNotIn('src/publish_opportunities.py', calls)

    def test_archive_confirmation_happens_only_after_dashboard_push(self):
        code, calls, log = self.run_script('success')
        self.assertEqual(code, 0)
        self.assertLess(calls.index('git push'), calls.index('src/publish_opportunities.py'))
        self.assertEqual(calls.count('git push'), 2)

    def test_failed_web_confirmation_does_not_publish_archive(self):
        code, calls, log = self.run_script('verification_failure')
        self.assertNotEqual(code, 0)
        self.assertEqual(calls.count('git push'), 1)
        self.assertNotIn('Archive opportunities from verified public dashboard', calls)

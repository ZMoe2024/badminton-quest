import argparse
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from badminton_reservation import workflow, compat, cli
from badminton_reservation.session import LoginRequired

CONFIG = {'venue': '主馆羽毛球场7', 'date': '2026-09-19', 'start': '12:00', 'end': '14:00'}


class WorkflowTests(unittest.TestCase):
    @patch.object(workflow, 'execute')
    @patch.object(workflow.session_store, 'save')
    @patch.object(workflow.session_store, 'load', return_value={'token': 'old'})
    @patch.object(workflow, 'ensure_session', return_value=({'token': 'new'}, {'valid': True, 'renewed': True}))
    def test_renewed_credentials_saved_and_passed_to_booking(self, ensure, load, save, execute):
        execute.return_value = {'submission': {'outcome': 'rejected'}}
        output = workflow.book(CONFIG, submit=True, session_file='unused.dpapi')
        save.assert_called_once_with(Path('unused.dpapi'), {'token': 'new'})
        execute.assert_called_once_with({'token': 'new'}, CONFIG, submit=True)
        self.assertTrue(output['authentication']['renewed'])

    @patch.object(workflow, 'execute')
    @patch.object(workflow, 'ensure_session', side_effect=LoginRequired('login required'))
    def test_login_failure_never_submits(self, ensure, execute):
        with self.assertRaises(LoginRequired): workflow.book(CONFIG, submit=True, credentials={})
        execute.assert_not_called()

    @patch.object(workflow, 'execute', return_value={'submission': {'outcome': 'unknown'}})
    @patch.object(workflow, 'authenticate', return_value=({}, {'valid': True}))
    def test_unknown_submission_is_not_retried(self, auth, execute):
        self.assertEqual(workflow.book(CONFIG, submit=True)['submission']['outcome'], 'unknown')
        execute.assert_called_once()

    @patch.object(workflow, 'authenticate')
    def test_bad_configuration_does_not_load_session(self, authenticate):
        with self.assertRaises(ValueError): workflow.book(CONFIG | {'end': '10:00'})
        authenticate.assert_not_called()

    @patch.object(compat, 'main', return_value=2)
    def test_legacy_submit_uses_same_cli_and_exit_code(self, main):
        self.assertEqual(compat.booking_main(['--submit', '--config', 'example.json']), 2)
        main.assert_called_once_with(['submit', '--config', 'example.json'])

    @patch.object(compat, 'main', return_value=0)
    def test_legacy_default_only_checks(self, main):
        self.assertEqual(compat.booking_main([]), 0)
        main.assert_called_once_with(['check'])

    def test_missing_session_fails_without_waiting_for_stdin(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(workflow, 'DEFAULT_SESSION', Path(folder) / 'absent.dpapi'):
            with self.assertRaisesRegex(ValueError, 'auth-import'):
                workflow.authenticate()


if __name__ == '__main__': unittest.main()

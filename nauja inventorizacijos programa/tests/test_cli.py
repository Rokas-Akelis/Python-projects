import unittest
from unittest.mock import patch

import path_setup  # noqa: F401

import cli


class TestCLI(unittest.TestCase):
    def test_cli_no_args(self):
        self.assertEqual(cli.main([]), 1)

    def test_cli_merge_csv(self):
        calls = []

        def fake_merge(csv_path=None):
            calls.append(csv_path)

        with patch.object(cli, "merge_wc_csv", fake_merge):
            rc = cli.main(["--merge-csv", "--csv-path", "x.csv"])

        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["x.csv"])

    def test_cli_pull_and_push(self):
        calls = []

        with patch.object(cli, "pull_products_from_wc", lambda: calls.append("pull")), patch.object(
            cli, "sync_prices_and_stock_to_wc", lambda: calls.append("push")
        ):
            rc_pull = cli.main(["--pull-wc"])
            rc_push = cli.main(["--push-wc"])

        self.assertEqual(rc_pull, 0)
        self.assertEqual(rc_push, 0)
        self.assertEqual(calls, ["pull", "push"])

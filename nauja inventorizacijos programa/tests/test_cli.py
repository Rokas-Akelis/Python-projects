import cli


def test_cli_no_args():
    assert cli.main([]) == 1


def test_cli_merge_csv(monkeypatch):
    calls = []

    def fake_merge(csv_path=None):
        calls.append(csv_path)

    monkeypatch.setattr(cli, "merge_wc_csv", fake_merge)
    rc = cli.main(["--merge-csv", "--csv-path", "x.csv"])
    assert rc == 0
    assert calls == ["x.csv"]


def test_cli_pull_and_push(monkeypatch):
    calls = []

    monkeypatch.setattr(cli, "pull_products_from_wc", lambda: calls.append("pull"))
    monkeypatch.setattr(cli, "sync_prices_and_stock_to_wc", lambda: calls.append("push"))

    rc_pull = cli.main(["--pull-wc"])
    rc_push = cli.main(["--push-wc"])

    assert rc_pull == 0
    assert rc_push == 0
    assert calls == ["pull", "push"]

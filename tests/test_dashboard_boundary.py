from dashboard.app import MESSAGE, main


def test_dashboard_boundary_is_explicit(capsys) -> None:
    assert main() == 0
    assert capsys.readouterr().out.strip() == MESSAGE
    assert "Phase 11" in MESSAGE
    assert "reports/" in MESSAGE

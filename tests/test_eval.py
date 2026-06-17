from askfaro_progressive_context import KeywordNavigator, NavCase, run_case, run_eval


def _cases(cases):
    return [NavCase(query=c["query"], target=c["target"]) for c in cases]


def test_baseline_navigates_above_floor(manifest, cases):
    report = run_eval(manifest, KeywordNavigator(), _cases(cases))
    assert report.n == len(cases)
    # The deterministic baseline should clear a low bar on good descriptors.
    assert report.navigation_success >= 0.5
    assert 0.0 <= report.first_hop_precision <= 1.0


def test_successful_case_reaches_leaf_directly(manifest):
    case = NavCase(query="send a private message to a teammate", target="channels.dm")
    result = run_case(manifest, KeywordNavigator(), case)
    assert result.success
    # branch then leaf == 2 hops
    assert result.hops == 2
    assert result.first_hop_correct
    assert result.path[-1] == "channels.dm"


def test_report_is_serializable(manifest, cases):
    report = run_eval(manifest, KeywordNavigator(), _cases(cases))
    d = report.to_dict()
    assert "navigation_success" in d and "cases" in d


def test_reserve_lowers_success(manifest, cases):
    # With a brutal reserve, large leaves become unaffordable, so the
    # navigator can no longer reach them and success drops.
    base = run_eval(manifest, KeywordNavigator(), _cases(cases)).navigation_success
    tight = run_eval(
        manifest, KeywordNavigator(), _cases(cases), reserve=manifest.variant.budget - 1200
    ).navigation_success
    assert tight < base

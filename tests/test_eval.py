from askfaro_progressive_context import KeywordNavigator, NavCase, Runtime, run_case, run_eval


def _cases(cases):
    return [NavCase(query=c["query"], target=c["target"]) for c in cases]


def test_use_facets_surfaces_matched_leaves_only(manifest):
    # The example map facets `posts.draft` as kind=template, verb=create — the only
    # such leaf. Filter-first should surface it directly and never expand outside
    # the matched set (no tree descent through unrelated branches).
    facet = {"kind": "template", "verb": "create"}
    matched = set(Runtime(manifest).find_by_facets(**facet))
    assert matched == {"posts.draft"}
    case = NavCase("draft a new social post", "posts.draft", facet=facet)
    result = run_case(manifest, KeywordNavigator(), case, use_facets=True)
    assert result.success and result.path == ["posts.draft"]


def test_use_related_rescues_cross_link_target(manifest):
    # `recurring.create` is a see-also of `posts.schedule` (a different branch).
    # A run that lands on posts.schedule reaches it only with use_related on.
    case = NavCase("queue a post for future publishing", "recurring.create")
    off = run_case(manifest, KeywordNavigator(), case, budget=100_000, use_related=False)
    on = run_case(manifest, KeywordNavigator(), case, budget=100_000, use_related=True)
    assert "posts.schedule" in on.path  # the walk lands on the linked sibling
    assert on.success and on.path[-1] == "recurring.create"
    assert not off.success  # without the see-also edge the target is unreachable here


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

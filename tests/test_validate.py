import copy

from faro_progressive_context import structural_errors


def test_example_is_valid(manifest_dict):
    assert structural_errors(manifest_dict) == []


def test_missing_what(manifest_dict):
    m = copy.deepcopy(manifest_dict)
    del m["nodes"]["posts.draft"]["what"]
    errs = structural_errors(m)
    assert any("missing 'what'" in e for e in errs)


def test_dangling_child(manifest_dict):
    m = copy.deepcopy(manifest_dict)
    m["nodes"]["posts"]["children"].append("does.not.exist")
    errs = structural_errors(m)
    assert any("not found in nodes" in e for e in errs)


def test_branch_and_leaf_are_mutually_exclusive(manifest_dict):
    m = copy.deepcopy(manifest_dict)
    m["nodes"]["posts"]["payload"] = {"ref": "node://posts"}
    errs = structural_errors(m)
    assert any("exactly one of children/payload" in e for e in errs)


def test_cycle_detected(manifest_dict):
    m = copy.deepcopy(manifest_dict)
    # make a leaf into a branch pointing back at its parent
    m["nodes"]["posts.draft"].pop("payload")
    m["nodes"]["posts.draft"]["children"] = ["posts"]
    errs = structural_errors(m)
    assert any("cycle detected" in e for e in errs)


def test_bad_version(manifest_dict):
    m = copy.deepcopy(manifest_dict)
    m["pcx_version"] = "9.9"
    assert any("pcx_version" in e for e in structural_errors(m))

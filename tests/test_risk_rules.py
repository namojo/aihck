"""규칙마다 examples.hit는 걸리고 examples.miss는 안 걸려야 한다."""
import pytest

from rfpharness.risk import load_rules, match_rule_text, normalize_value

RULES = load_rules()


@pytest.mark.parametrize("rule", RULES, ids=[r["id"] for r in RULES])
def test_examples_present(rule):
    assert rule.get("examples", {}).get("hit"), f"{rule['id']}: examples.hit 없음"
    assert rule.get("examples", {}).get("miss"), f"{rule['id']}: examples.miss 없음"
    assert rule.get("why") and rule.get("negotiation_point") and rule.get("basis")


@pytest.mark.parametrize("rule", RULES, ids=[r["id"] for r in RULES])
def test_hit_example_matches(rule):
    assert match_rule_text(rule, rule["examples"]["hit"]), f"{rule['id']} hit 예문이 걸리지 않음"


@pytest.mark.parametrize("rule", RULES, ids=[r["id"] for r in RULES])
def test_miss_example_does_not_match(rule):
    assert not match_rule_text(rule, rule["examples"]["miss"]), f"{rule['id']} miss 예문이 걸림"


def test_rule_ids_unique():
    ids = [r["id"] for r in RULES]
    assert len(ids) == len(set(ids))
    assert len(ids) == 20


@pytest.mark.parametrize("text,expected", [
    ("1000분의 2.5", 0.25), ("2.5/1000", 0.25), ("0.25%", 0.25), ("1.25‰", 0.125),
])
def test_rate_normalization(text, expected):
    v, _ = normalize_value("rate_per_day_percent", text)
    assert v == pytest.approx(expected)


def test_years_normalization():
    assert normalize_value("years", "하자보수 18개월")[0] == pytest.approx(1.5)
    assert normalize_value("years", "하자보수 3년")[0] == 3

"""계약서, 정답지(golden), 시나리오 파일 로더."""

from __future__ import annotations

from pathlib import Path

import yaml

from .schemas import Customer, ForceMajeureJudgment, PenaltyTerms, Scenario

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = ROOT / "contracts"
GOLDEN_DIR = CONTRACT_DIR / "golden"
SCENARIO_DIR = ROOT / "scenarios"


def load_customers() -> list[Customer]:
    raw = yaml.safe_load((CONTRACT_DIR / "customers.yaml").read_text(encoding="utf-8"))
    return [Customer(**{k: v for k, v in c.items() if k != "contract_file"}) for c in raw["customers"]]


def contract_file(customer_id: str) -> Path:
    raw = yaml.safe_load((CONTRACT_DIR / "customers.yaml").read_text(encoding="utf-8"))
    for c in raw["customers"]:
        if c["id"] == customer_id:
            return CONTRACT_DIR / c["contract_file"]
    raise KeyError(customer_id)


def load_contract_text(customer_id: str) -> str:
    return contract_file(customer_id).read_text(encoding="utf-8")


def load_golden_terms(customer_id: str) -> PenaltyTerms:
    raw = yaml.safe_load((GOLDEN_DIR / f"{customer_id}.yaml").read_text(encoding="utf-8"))
    return PenaltyTerms(**raw["terms"])


def load_golden_judgment(customer_id: str, scenario_id: str) -> ForceMajeureJudgment:
    raw = yaml.safe_load((GOLDEN_DIR / f"{customer_id}.yaml").read_text(encoding="utf-8"))
    j = dict(raw["judgments"][scenario_id])
    terms = raw["terms"]
    cite = (terms.get("force_majeure") or {}).get("citation")
    if j.get("has_clause") and cite and "citation" not in j:
        j["citation"] = cite
    j.setdefault("conditions_met", {})
    return ForceMajeureJudgment(customer_id=customer_id, **j)


def list_scenarios() -> list[str]:
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.yaml"))


def load_scenario(scenario_id: str) -> Scenario:
    raw = yaml.safe_load((SCENARIO_DIR / f"{scenario_id}.yaml").read_text(encoding="utf-8"))
    return Scenario(**raw)

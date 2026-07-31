from fastapi import APIRouter, HTTPException

from app.core.constants import Tags
from app.schemas.override_rules import (
    OverrideRuleCreate,
    OverrideRuleResponse,
    OverrideRuleToggle,
    OverrideRuleUpdate,
)
from app.services import override_rules_repository

router = APIRouter(prefix="/override-rules", tags=[Tags.OVERRIDE_RULES])


@router.get("", response_model=list[OverrideRuleResponse], summary="List all override rules")
def list_rules() -> list[OverrideRuleResponse]:
    return override_rules_repository.list_all()


@router.post("", response_model=OverrideRuleResponse, summary="Create an override rule")
def create_rule(rule: OverrideRuleCreate) -> OverrideRuleResponse:
    return override_rules_repository.create(rule.model_dump())


@router.put("/{rule_id}", response_model=OverrideRuleResponse, summary="Update an override rule")
def update_rule(rule_id: int, rule: OverrideRuleUpdate) -> OverrideRuleResponse:
    try:
        return override_rules_repository.update(rule_id, rule.model_dump())
    except IndexError:
        raise HTTPException(status_code=404, detail="Override rule not found")


@router.patch("/{rule_id}/toggle", response_model=OverrideRuleResponse, summary="Toggle a rule's active status")
def toggle_rule(rule_id: int, body: OverrideRuleToggle) -> OverrideRuleResponse:
    try:
        return override_rules_repository.toggle(rule_id, body.is_active)
    except IndexError:
        raise HTTPException(status_code=404, detail="Override rule not found")


@router.delete("/{rule_id}", status_code=204, summary="Delete an override rule")
def delete_rule(rule_id: int) -> None:
    override_rules_repository.delete(rule_id)

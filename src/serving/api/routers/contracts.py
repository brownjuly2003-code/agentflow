from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request

from src.serving.semantic_layer.contract_registry import SchemaContract
from src.serving.semantic_layer.schema_evolution import (
    EvolutionChecker,
    has_version_bump,
    load_schema,
)

router = APIRouter(tags=["contracts"])


def _get_registry(request: Request):
    return request.app.state.catalog.contract_registry


def _base_contract_schema(contract: SchemaContract) -> dict[str, Any]:
    if contract.source_path is not None:
        return load_schema(contract.source_path)
    return cast(dict[str, Any], contract.to_dict())


@router.get("/contracts")
async def list_contracts(request: Request):
    registry = _get_registry(request)
    return {
        "contracts": [
            contract.summary().to_dict()
            for contract in registry.list_contracts()
        ]
    }


@router.get("/contracts/{entity}/diff/{from_version}/{to_version}")
async def diff_contract_versions(
    entity: str,
    from_version: str,
    to_version: str,
    request: Request,
):
    registry = _get_registry(request)
    try:
        return registry.diff(entity, from_version, to_version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/contracts/{entity}/validate")
async def validate_contract(
    entity: str,
    candidate_schema: dict[str, Any],
    request: Request,
):
    registry = _get_registry(request)
    contract = registry.get_latest_stable(entity)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Unknown contract: {entity}")

    candidate_entity = candidate_schema.get("entity")
    if candidate_entity not in (None, entity):
        raise HTTPException(
            status_code=400,
            detail=f"Schema entity mismatch: expected {entity}",
        )

    base_schema = _base_contract_schema(contract)
    target_schema = dict(candidate_schema)
    target_schema["entity"] = entity
    target_schema["version"] = str(target_schema.get("version", contract.version)).lstrip("v")

    report = EvolutionChecker().check(base_schema, target_schema)
    return {
        "entity": entity,
        "base_version": base_schema.get("version", contract.version),
        "candidate_version": target_schema["version"],
        **report.to_dict(),
        "requires_version_bump": report.is_breaking and not has_version_bump(
            base_schema, target_schema
        ),
    }


@router.get("/contracts/{entity}/{version}")
async def get_contract_version(
    entity: str,
    version: str,
    request: Request,
):
    registry = _get_registry(request)
    try:
        return registry.get_contract(entity, version).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/contracts/{entity}")
async def get_latest_contract(entity: str, request: Request):
    registry = _get_registry(request)
    contract = registry.get_latest_stable(entity)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Unknown contract: {entity}")
    return contract.to_dict()

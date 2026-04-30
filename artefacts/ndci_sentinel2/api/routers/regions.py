"""
Router: /api/regions — CRUD de regiões geográficas desenhadas no frontend.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import LAGOAS
from storage.database import get_db
from storage.repositories.geo_regions import GeoRegionRepository

router = APIRouter(prefix="/api/regions", tags=["Regions"])


class RegionCreate(BaseModel):
    nome: str
    descricao: Optional[str] = None
    polygon: list                    # [[lon, lat], ...]
    lagoa: Optional[str] = None
    categoria: str = "setor_lagoa"
    ativo: bool = True
    min_pixels: Optional[int] = None


class RegionUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    polygon: Optional[list] = None
    categoria: Optional[str] = None
    ativo: Optional[bool] = None
    min_pixels: Optional[int] = None


@router.get("")
def list_regions(
    lagoa: Optional[str] = None,
    categoria: Optional[str] = None,
    ativo: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """Lista regiões, opcionalmente filtradas por lagoa, categoria ou status ativo."""
    repo = GeoRegionRepository(db)
    regions = repo.get_by_lagoa(lagoa, only_active=False) if lagoa is not None else repo.get_all()
    if categoria is not None:
        regions = [r for r in regions if r.categoria == categoria]
    if ativo is not None:
        regions = [r for r in regions if bool(r.ativo) == ativo]
    return [_serialize(r) for r in regions]


@router.get("/lagoas")
def list_lagoas():
    """Retorna todas as lagoas configuradas (com ou sem dados) para popular selects."""
    return {"lagoas": sorted(LAGOAS.keys())}


@router.post("", status_code=201)
def create_region(body: RegionCreate, db: Session = Depends(get_db)):
    """Cria uma nova região geográfica."""
    repo = GeoRegionRepository(db)
    try:
        region = repo.create(
            nome=body.nome,
            descricao=body.descricao,
            polygon=body.polygon,
            lagoa=body.lagoa,
            categoria=body.categoria,
            ativo=1 if body.ativo else 0,
            min_pixels=body.min_pixels,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _serialize(region)


@router.put("/{region_id}")
def update_region(region_id: int, body: RegionUpdate, db: Session = Depends(get_db)):
    """Atualiza campos de uma região existente."""
    repo = GeoRegionRepository(db)
    updates = body.model_dump(exclude_unset=True)
    if "ativo" in updates:
        updates["ativo"] = 1 if updates["ativo"] else 0
    region = repo.update(region_id, **updates)
    if not region:
        raise HTTPException(status_code=404, detail="Região não encontrada.")
    return _serialize(region)


@router.delete("/{region_id}", status_code=204)
def delete_region(region_id: int, db: Session = Depends(get_db)):
    """Remove uma região permanentemente."""
    repo = GeoRegionRepository(db)
    if not repo.delete(region_id):
        raise HTTPException(status_code=404, detail="Região não encontrada.")


def _serialize(r) -> dict:
    return {
        "id":         r.id,
        "nome":       r.nome,
        "descricao":  r.descricao,
        "polygon":    r.polygon,
        "lagoa":      r.lagoa,
        "categoria":  r.categoria,
        "ativo":      bool(r.ativo),
        "min_pixels": r.min_pixels,
        "criado_em":  r.criado_em.isoformat() if r.criado_em else None,
    }

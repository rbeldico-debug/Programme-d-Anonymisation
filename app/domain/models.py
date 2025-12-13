from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class RedactionDetail:
    """Détail d'une zone masquée pour l'audit."""
    page: int
    text: str
    entity_type: str
    source: str         # "PRESIDIO" ou "LLM"
    score: float

@dataclass
class PipelineResult:
    """Objet standardisé retourné par le pipeline pour chaque fichier traité."""
    file: str
    status: str          # "SUCCESS", "FAILED"
    entities_found: int
    error: Optional[str] = None
    # Liste des détails pour l'audit (vide par défaut)
    details: List[RedactionDetail] = field(default_factory=list)
"""Allergènes ajoutés dans Paramètres (en plus des 14 allergènes réglementaires).

Repris de l'ancienne version (Paramètres → allergènes et icônes) : un allergène ajouté
apparaît sur la fiche, dans ce que lit ChatGPT et sur le PDF, avec son icône s'il en a une.
"""
from __future__ import annotations

import io
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.erreurs import ErreurMetier, introuvable
from ..domain.normalisation import ALLERGENES, cle_allergene, texte_court
from ..models import Allergene, Fiche, Produit
from .contexte import Acteur, journaliser

ICONE_MAX_OCTETS = 2 * 1024 * 1024


def supplementaires(session: Session) -> dict[str, str]:
    return {a.cle: a.libelle for a in session.scalars(select(Allergene).order_by(Allergene.libelle))}


def tous(session: Session) -> dict[str, str]:
    """Clé → libellé : les 14 allergènes réglementaires puis ceux ajoutés dans Paramètres."""
    return {**ALLERGENES, **supplementaires(session)}


def icones(session: Session) -> dict[str, bytes]:
    return {a.cle: a.icone for a in session.scalars(select(Allergene).where(Allergene.icone.is_not(None)))}


def allergene_dict(a: Allergene) -> dict[str, Any]:
    return {"cle": a.cle, "libelle": a.libelle, "icone": a.icone is not None}


def lister(session: Session) -> list[dict[str, Any]]:
    return [allergene_dict(a) for a in session.scalars(select(Allergene).order_by(Allergene.libelle))]


def normaliser_icone(contenu: bytes) -> bytes:
    """Icône carrée en PNG (comme l'ancienne version) : tout format d'image lisible par Pillow."""
    from PIL import Image, UnidentifiedImageError

    if not contenu:
        raise ErreurMetier("champ_obligatoire", "Le fichier de l'icône est vide.", champ="icone")
    if len(contenu) > ICONE_MAX_OCTETS:
        raise ErreurMetier("regle_metier", "Icône trop lourde (2 Mo au maximum).", champ="icone")
    try:
        with Image.open(io.BytesIO(contenu)) as image:
            image = image.convert("RGBA")
            image.thumbnail((300, 300))
            cote = max(image.size)
            carre = Image.new("RGBA", (cote, cote), (255, 255, 255, 0))
            carre.paste(image, ((cote - image.width) // 2, (cote - image.height) // 2))
            sortie = io.BytesIO()
            carre.save(sortie, format="PNG")
            return sortie.getvalue()
    except (UnidentifiedImageError, OSError):
        raise ErreurMetier("valeur_non_permise", "Fichier d'icône illisible (PNG, JPEG…).", champ="icone")


def creer(session: Session, acteur: Acteur, libelle: Any, cle: Optional[str] = None,
          icone: Optional[bytes] = None) -> Allergene:
    acteur.exiger("admin")
    libelle = texte_court(libelle, "libellé", 100, obligatoire=True)
    k = cle_allergene(cle or libelle)
    if not k:
        raise ErreurMetier("valeur_non_permise", "Libellé d'allergène invalide.", champ="libelle")
    existants = tous(session)
    if k in existants or any(cle_allergene(v) == cle_allergene(libelle) for v in existants.values()):
        raise ErreurMetier("doublon_probable", f"L'allergène « {libelle} » existe déjà.", champ="libelle")
    a = Allergene(cle=k, libelle=libelle, icone=normaliser_icone(icone) if icone else None)
    session.add(a)
    session.flush()
    journaliser(session, acteur, "allergene.creer", "allergene", None, f"Allergène ajouté : {libelle} ({k})")
    session.commit()
    return a


def _obtenir(session: Session, cle: str) -> Allergene:
    a = session.get(Allergene, cle)
    if a is None:
        if cle in ALLERGENES:
            raise ErreurMetier("interdit", "Les 14 allergènes réglementaires ne se modifient pas.")
        raise introuvable("Allergène")
    return a


def modifier(session: Session, acteur: Acteur, cle: str, libelle: Any = None, icone: Optional[bytes] = None,
             retirer_icone: bool = False) -> Allergene:
    acteur.exiger("admin")
    a = _obtenir(session, cle)
    if libelle is not None:
        a.libelle = texte_court(libelle, "libellé", 100, obligatoire=True)
    if icone:
        a.icone = normaliser_icone(icone)
    elif retirer_icone:
        a.icone = None
    journaliser(session, acteur, "allergene.modifier", "allergene", None, f"Allergène modifié : {a.libelle} ({a.cle})")
    session.commit()
    return a


def supprimer(session: Session, acteur: Acteur, cle: str) -> None:
    """Refusé si une fiche ou un produit l'utilise : il resterait imprimé sans libellé."""
    acteur.exiger("admin")
    a = _obtenir(session, cle)
    utilise = any(cle in (f.allergenes or []) for f in session.scalars(select(Fiche)))
    utilise = utilise or any(cle in (p.allergenes or []) for p in session.scalars(select(Produit)))
    if utilise:
        raise ErreurMetier("regle_metier", f"« {a.libelle} » est utilisé sur des fiches ou des produits : "
                                           "il ne peut pas être supprimé (le renommer si besoin).")
    session.delete(a)
    journaliser(session, acteur, "allergene.supprimer", "allergene", None, f"Allergène supprimé : {a.libelle} ({a.cle})")
    session.commit()

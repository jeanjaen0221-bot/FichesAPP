"""Contrôle des fiches à venir : ce qui est à corriger ou à vérifier avant le service.

Relit chaque fiche (créée sur le site ou par ChatGPT) avec les règles de l'outil et les
consignes de ChatGPT, sans rien modifier. Deux niveaux :
- « a_corriger » : la fiche enfreint une règle ou sera mal imprimée ;
- « a_verifier » : à regarder, ce n'est pas forcément une erreur.
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..domain.erreurs import ErreurMetier
from ..domain.normalisation import LIBELLES_TYPES, TYPES_PLATS, cle
from ..domain.regles import LIBELLES_STATUTS_FICHE, appliquer_regles_fiche
from ..models import Fiche, Produit
from ..pdf.documents import _REMPLISSAGE, est_choix_du_chef
from .fiches import CHATGPT_COMMENTAIRE_MAX, CHATGPT_NOTES_MAX, aujourd_hui

A_CORRIGER, A_VERIFIER = "a_corriger", "a_verifier"
_TITRE_CLIENT = re.compile(r"^(m|mr|mme|mlle|mrs|ms|monsieur|madame|dr)\.?\s", re.IGNORECASE)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_SOURCE_DANS_NOTES = re.compile(r"gmail|thread|identifiant|e-?mail du|€|\beur\b|\btva\b", re.IGNORECASE)


def _probleme(niveau: str, message: str) -> dict[str, str]:
    return {"niveau": niveau, "message": message}


def controler_fiche(fiche: Fiche, carte: dict[str, Produit]) -> list[dict[str, str]]:
    """Problèmes d'une fiche. `carte` : produits actifs par nom normalisé."""
    problemes: list[dict[str, str]] = []
    lignes = list(fiche.lignes)

    # Règles de l'outil (données saisies avant une règle, ou couverts changés depuis).
    try:
        _, alertes = appliquer_regles_fiche(fiche.couverts, fiche.formule_repas, lignes)
        problemes += [_probleme(A_VERIFIER, a) for a in alertes]
    except ErreurMetier as erreur:
        problemes.append(_probleme(A_CORRIGER, erreur.message))

    # Chaque convive a-t-il son entrée, son plat, son dessert ?
    sharing = any(est_choix_du_chef(l.libelle) for l in lignes)
    if not sharing:
        for t in TYPES_PLATS:
            total = sum(l.quantite for l in lignes if l.type == t)
            if 0 < total < fiche.couverts:
                problemes.append(_probleme(
                    A_VERIFIER, f"{total} {LIBELLES_TYPES[t]}(s) pour {fiche.couverts} couverts."))

    for l in lignes:
        nom = f"« {l.libelle} »"
        if l.produit is not None:
            if not l.produit.actif:
                problemes.append(_probleme(A_VERIFIER, f"{nom} n'est plus sur la carte (mis de côté)."))
            if l.produit.prix_centimes is None:
                problemes.append(_probleme(A_VERIFIER, f"{nom} : prix manquant (menu Carte ou Prix)."))
        elif cle(l.libelle).startswith("alternative"):
            problemes.append(_probleme(A_VERIFIER, f"{nom} : alternative à faire choisir par le chef."))
        else:
            base = re.split(r"\s+[—–-]\s+", l.libelle, maxsplit=1)[0]
            produit = carte.get(cle(base))
            if produit is None:
                problemes.append(_probleme(A_VERIFIER, f"{nom} : hors carte."))
            elif produit.prix_centimes is None:
                problemes.append(_probleme(A_VERIFIER, f"{nom} : prix manquant (menu Carte ou Prix)."))
        commentaire = (l.commentaire or "").strip()
        if commentaire:
            phrases = [p for p in re.split(r"(?<=[.!?])\s+", commentaire) if p]
            if any(_REMPLISSAGE.match(p.strip()) for p in phrases):
                problemes.append(_probleme(A_CORRIGER, f"{nom} : commentaire inutile (« {commentaire[:60]} »)."))
            elif len(commentaire) > CHATGPT_COMMENTAIRE_MAX or "\n" in commentaire:
                problemes.append(_probleme(
                    A_CORRIGER, f"{nom} : commentaire trop long ({len(commentaire)} caractères) ; "
                                "une variante va sur sa propre ligne avec sa quantité."))

    formule = fiche.formule_repas
    if formule is not None and formule.produit is not None and formule.produit.prix_centimes is None:
        problemes.append(_probleme(A_VERIFIER, f"Formule « {formule.nom} » : prix manquant (menu Prix)."))

    for champ, titre in (("notes_salle", "Notes salle"), ("notes_cuisine", "Notes cuisine")):
        notes = (getattr(fiche, champ) or "").strip()
        if len(notes) > CHATGPT_NOTES_MAX:
            problemes.append(_probleme(A_CORRIGER, f"{titre} trop longues ({len(notes)} caractères, "
                                                   f"{CHATGPT_NOTES_MAX} au plus) : elles s'impriment."))
        if _SOURCE_DANS_NOTES.search(notes):
            problemes.append(_probleme(A_VERIFIER, f"{titre} : source Gmail, prix ou TVA à retirer ?"))

    nom_client = fiche.client.nom or ""
    if _TITRE_CLIENT.match(nom_client) or _EMOJI.search(nom_client) or re.search(r"\d{1,2}[/.-]\d{1,2}", nom_client):
        problemes.append(_probleme(A_VERIFIER, f"Nom du client « {nom_client} » : sans titre, date ni emoji."))

    jours = (fiche.date - aujourd_hui()).days
    if fiche.statut == "brouillon" and jours <= 7:
        problemes.append(_probleme(A_VERIFIER, "Encore en brouillon : réservation pas confirmée."))
    elif fiche.statut == "confirmee" and jours <= 2:
        problemes.append(_probleme(A_VERIFIER, "Pas encore finale : à valider pour la cuisine."))
    return problemes


def controler(session: Session, jours: int = 60) -> dict[str, Any]:
    """Fiches à venir (aujourd'hui + `jours`), sauf annulées et réalisées, avec leurs problèmes."""
    debut = aujourd_hui()
    fiches = list(session.scalars(
        select(Fiche).options(selectinload(Fiche.lignes))
        .where(Fiche.date >= debut, Fiche.date <= debut + timedelta(days=jours),
               Fiche.statut.in_(("brouillon", "confirmee", "finale")))
        .order_by(Fiche.date, Fiche.heure)))
    carte = {cle(p.nom): p for p in session.scalars(select(Produit).where(Produit.actif.is_(True)))}
    resultats = []
    for f in fiches:
        problemes = controler_fiche(f, carte)
        if problemes:
            problemes.sort(key=lambda p: p["niveau"] != A_CORRIGER)
            resultats.append({
                "id": str(f.id), "date": f.date.isoformat(), "heure": f.heure.strftime("%H:%M"),
                "client": f.client.nom, "couverts": f.couverts, "statut": f.statut,
                "statut_libelle": LIBELLES_STATUTS_FICHE[f.statut], "problemes": problemes,
            })
    return {"controlees": len(fiches), "jours": jours, "fiches": resultats}

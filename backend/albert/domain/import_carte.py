"""Lecture d'une liste de plats collée dans le menu Prix (« ajouter une liste »).

Reprend l'« ajout en masse » de l'ancienne version (une ligne par plat, « Nom | type »)
et accepte aussi une carte copiée telle quelle :

    Entrées                                  ← intertitre : change le type des lignes suivantes
    Carpaccio de bœuf ........... 14,50 €    ← prix en fin de ligne (points de conduite permis)
    Croquettes de crevettes | entrée | 16    ← champs séparés par « | », tabulation ou « ; »
    Planche apéro | supplément               ← sans prix : « prix à compléter »

Fonction pure : elle ne lit pas la base. Chaque ligne lue porte son numéro et, si elle
est refusée, la raison, pour que l'équipe corrige le texte avant d'importer.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Optional

from .argent import lire_euros
from .erreurs import ErreurMetier
from .normalisation import cle

CATEGORIES_IMPORT = ("entree", "plat", "dessert", "supplement")
NOM_MAX = 200
LIGNES_MAX = 500

_TYPES = {
    "entree": "entree", "entrees": "entree", "starter": "entree", "starters": "entree", "voorgerecht": "entree",
    "voorgerechten": "entree", "hors d oeuvre": "entree", "hors d oeuvres": "entree", "a partager": "entree",
    "plat": "plat", "plats": "plat", "plat principal": "plat", "plats principaux": "plat", "main": "plat",
    "mains": "plat", "main course": "plat", "main courses": "plat", "hoofdgerecht": "plat", "hoofdgerechten": "plat",
    "dessert": "dessert", "desserts": "dessert", "nagerecht": "dessert", "nagerechten": "dessert",
    "supplement": "supplement", "supplements": "supplement", "extra": "supplement", "extras": "supplement",
    "accompagnement": "supplement", "accompagnements": "supplement", "sides": "supplement",
}

# Prix en fin de ligne : « 14,50 », « 14.50 € », « € 14 », « 14 eur ». Un entier nu n'est un prix
# que s'il est annoncé (€, points de conduite) : « Tartare 200 » ou « Menu 3 » restent des noms.
_PRIX_FIN = re.compile(
    r"(?P<avant>\s*(?:\.{2,}|…+|_{2,}|-{2,})?\s*)(?P<euro1>€\s*)?(?P<montant>\d{1,4}(?:[.,]\d{1,2})?)"
    r"\s*(?P<euro2>€|eur\b|euros?\b)?\s*$",
    re.IGNORECASE,
)
_DECOR = re.compile(r"^[\W_]+$")


@dataclass
class LigneLue:
    numero: int  # numéro de la ligne dans le texte collé (à partir de 1)
    texte: str
    nom: Optional[str] = None
    categorie: Optional[str] = None
    prix_centimes: Optional[int] = None
    erreur: Optional[str] = None


def lire_type(valeur: str) -> Optional[str]:
    return _TYPES.get(re.sub(r"\s+", " ", re.sub(r"[^a-z]", " ", cle(valeur))).strip())


def _intertitre(ligne: str) -> Optional[str]:
    """« Entrées », « PLATS : », « — Desserts — » → le type ; sinon None."""
    texte = re.sub(r"[\s:–—\-*#•]+$", "", re.sub(r"^[\s:–—\-*#•]+", "", ligne))
    return lire_type(texte) if len(texte) <= 40 else None


def _nettoyer_nom(nom: str) -> str:
    nom = re.sub(r"(?:\s*(?:\.{2,}|…+|_{2,}|-{2,}))+\s*$", "", nom)  # points de conduite restés seuls
    nom = re.sub(r"^\s*(?:[-*•·]\s+|\d{1,3}[.)]\s+)", "", nom)  # puce ou numéro en début de ligne
    return re.sub(r"\s+", " ", nom).strip(" \t,;:")


def _prix_en_fin(ligne: str) -> tuple[str, Optional[int]]:
    m = _PRIX_FIN.search(ligne)
    if not m or m.start() == 0:
        return ligne, None
    annonce = m.group("euro1") or m.group("euro2") or re.search(r"[.…_\-]{2,}", m.group("avant") or "")
    decimal = re.search(r"[.,]\d{1,2}$", m.group("montant"))
    if not (annonce or decimal):
        return ligne, None
    if not (m.group("avant") or m.group("euro1")):  # « Menu14,50 » : collé au nom, pas un prix
        return ligne, None
    return ligne[: m.start()], lire_euros(m.group("montant"))


def _ligne_a_champs(numero: int, ligne: str, champs: list[str], courante: Optional[str]) -> LigneLue:
    lue = LigneLue(numero, ligne)
    nom = _nettoyer_nom(champs[0])
    reste = [c.strip() for c in champs[1:] if c.strip()]
    categorie, prix = courante, None
    for champ in reste:
        type_lu = lire_type(champ)
        if type_lu:
            categorie = type_lu
            continue
        try:
            prix = lire_euros(champ)
        except ErreurMetier:
            lue.erreur = (f"« {champ} » n'est ni un type (entrée, plat, dessert, supplément) "
                          "ni un prix (ex. 14,50).")
            return lue
    lue.nom, lue.categorie, lue.prix_centimes = nom, categorie, prix
    return lue


def lire_liste(texte: str, categorie_defaut: Optional[str] = None) -> list[LigneLue]:
    """Lit le texte collé, ligne par ligne. Les lignes vides et décoratives sont ignorées."""
    if categorie_defaut is not None and categorie_defaut not in CATEGORIES_IMPORT:
        raise ErreurMetier("valeur_non_permise", f"Type par défaut inconnu : {categorie_defaut!r}.",
                           champ="categorie_defaut", valeurs_permises=list(CATEGORIES_IMPORT))
    lignes = str(texte or "").replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ").split("\n")
    if sum(1 for l in lignes if l.strip()) > LIGNES_MAX:
        raise ErreurMetier("regle_metier", f"Liste trop longue : {LIGNES_MAX} lignes au plus par import.",
                           champ="texte")
    courante = categorie_defaut
    sortie: list[LigneLue] = []
    vus: dict[tuple[str, str], int] = {}
    for numero, brute in enumerate(lignes, start=1):
        ligne = brute.strip()
        if not ligne or _DECOR.match(ligne):
            continue
        separateur = next((s for s in ("|", "\t", ";") if s in ligne), None)
        if separateur is None:
            intertitre = _intertitre(ligne)
            if intertitre:
                courante = intertitre
                continue
            try:
                nom, prix = _prix_en_fin(ligne)
            except ErreurMetier:
                nom, prix = ligne, None
            lue = LigneLue(numero, ligne, _nettoyer_nom(nom), courante, prix)
        else:
            lue = _ligne_a_champs(numero, ligne, ligne.split(separateur), courante)
        if lue.erreur is None:
            if not lue.nom or len(lue.nom) < 2:
                lue.erreur = "Nom manquant."
            elif len(lue.nom) > NOM_MAX:
                lue.erreur = f"Nom trop long ({len(lue.nom)} caractères, {NOM_MAX} au plus)."
            elif lue.categorie is None:
                lue.erreur = ("Type inconnu : ajouter « | entrée » (ou plat, dessert, supplément), "
                              "un intertitre « Entrées » au-dessus, ou choisir un type par défaut.")
        if lue.erreur is None:
            cle_ligne = (lue.categorie, cle(lue.nom))
            if cle_ligne in vus:
                lue.erreur = f"En double dans la liste (déjà ligne {vus[cle_ligne]})."
            else:
                vus[cle_ligne] = numero
        sortie.append(lue)
    return sortie


# --------------------------------------------------------------- fichiers

def _recoller_lettres(s: str) -> str:
    """« C a r p a c c i o » (carte mise en page) → « Carpaccio »."""
    return re.sub(r"\b(?:\w ){2,}\w\b", lambda m: m.group(0).replace(" ", ""), s)


def texte_depuis_fichier(nom_fichier: str, contenu: bytes) -> str:
    """Texte d'une carte en PDF, en texte ou en CSV, à relire avant l'aperçu."""
    nom = (nom_fichier or "").lower()
    if nom.endswith(".pdf") or contenu[:5] == b"%PDF-":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            pages = PdfReader(io.BytesIO(contenu)).pages
            texte = "\n".join((page.extract_text() or "") for page in pages)
        except (PdfReadError, ValueError, KeyError):
            raise ErreurMetier("valeur_non_permise", "PDF illisible.", champ="fichier")
        texte = "\n".join(_recoller_lettres(l) for l in texte.splitlines())
        if not texte.strip():
            raise ErreurMetier("regle_metier", "Ce PDF ne contient pas de texte (image scannée ?) : "
                                               "copier la carte à la main.", champ="fichier")
        return texte
    for encodage in ("utf-8-sig", "cp1252"):
        try:
            texte = contenu.decode(encodage)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 décode presque tout
        raise ErreurMetier("valeur_non_permise", "Fichier texte illisible.", champ="fichier")
    if nom.endswith(".csv"):
        delimiteur = ";" if texte.count(";") >= texte.count(",") else ","
        rangs = [r for r in csv.reader(io.StringIO(texte), delimiter=delimiteur) if any(c.strip() for c in r)]
        if rangs and cle(rangs[0][0]) in ("nom", "name", "plat", "produit"):
            rangs = rangs[1:]  # ligne d'en-tête
        return "\n".join(" | ".join(c.strip() for c in r if c.strip()) for r in rangs)
    return texte

"""Fiches imprimées et ce que ChatGPT y écrit (retours de l'équipe sur l'ancienne version)."""
import io

import pytest
from pypdf import PdfReader

from albert.domain.erreurs import ErreurMetier
from albert.pdf.documents import commentaire_imprime, est_choix_du_chef, nom_fichier, pdf_fiche
from albert.services import fiches

from .test_fiches_devis import creer_fiche


def _pdf(session, fiche, variante="complete"):
    contenu = pdf_fiche(fiches.fiche_dict(session, fiches.obtenir(session, fiche.id)), variante)
    return PdfReader(io.BytesIO(contenu)).pages


def test_notes_plus_longues_qu_une_page(session, acteur_admin):
    # Une cellule de tableau ne se coupe pas : le PDF échouait (LayoutError) et la fiche
    # ne se téléchargeait plus.
    notes = "\n".join(f"- demande spéciale numéro {i}, à respecter pendant le service" for i in range(60))
    fiche, _ = creer_fiche(session, acteur_admin, notes_salle=notes)
    assert len(_pdf(session, fiche, "salle")) > 1


def test_notes_en_bas_de_page_sans_feuille_vide(session, acteur_admin):
    # Des notes finissant en bas de page envoyaient le seul bas du cadre sur une feuille vide.
    for n in range(1, 45):
        notes = "\n".join(f"- demande {i}" for i in range(n))
        fiche, _ = creer_fiche(session, acteur_admin, nom_client=f"Client {n}", notes_salle=notes,
                               lignes=[{"type": "plat", "libelle": "Steak", "quantite": 10}])
        pages = _pdf(session, fiche, "salle")
        assert all(p.extract_text().strip() for p in pages), f"feuille vide avec {n} lignes de notes"


@pytest.mark.parametrize("commentaire, imprime", [
    ("Préparation standard.", ""),
    ("Adaptation à valider par la cuisine.", ""),
    ("Sans viande ni poisson, si possible sans champignons. À valider par la cuisine.",
     "Sans viande ni poisson, si possible sans champignons."),
    ("sans sauce", "sans sauce"),
])
def test_commentaire_imprime_sans_remplissage(commentaire, imprime):
    assert commentaire_imprime(commentaire) == imprime


def test_choix_du_chef_laisse_une_ligne_pour_ecrire(session, acteur_admin):
    assert est_choix_du_chef("Chef’s choice, sharingdishes") and est_choix_du_chef("Choix du chef")
    assert not est_choix_du_chef("Poule faisane")
    fiche, _ = creer_fiche(session, acteur_admin, lignes=[{"type": "entree", "libelle": "Chef’s choice, sharingdishes", "quantite": 20}])
    assert "Choix du chef :" in "".join(p.extract_text() for p in _pdf(session, fiche, "cuisine"))


def test_nom_de_fichier_ascii():
    assert nom_fichier("fiche", "Dvořák / Łukasz") == "fiche_Dvorak_ukasz.pdf"
    nom_fichier("fiche", "Conseil de l’Union européenne").encode("latin-1")


def test_chatgpt_une_ligne_par_variante(session, acteur_admin, acteur_chatgpt):
    fiche, _ = creer_fiche(session, acteur_admin, couverts=37)
    long = "37 convives dont 6 végétariens : alternatives à valider. Parmi les 31 autres, 3 sans gluten."
    with pytest.raises(ErreurMetier, match="sa propre ligne"):
        fiches.ajouter_ligne(session, acteur_chatgpt, fiche.id,
                             {"type": "plat", "libelle": "Poule faisane", "quantite": 31, "commentaire": long})
    for libelle, q in (("Poule faisane", 28), ("Poule faisane — sans gluten", 3), ("Alternative végétarienne (à valider)", 6)):
        fiches.ajouter_ligne(session, acteur_chatgpt, fiche.id, {"type": "plat", "libelle": libelle, "quantite": q})
    assert {l.libelle: l.quantite for l in fiches.obtenir(session, fiche.id).lignes} == {
        "Poule faisane": 28, "Poule faisane — sans gluten": 3, "Alternative végétarienne (à valider)": 6}


def test_chatgpt_notes_courtes_mais_le_site_libre(session, acteur_admin, acteur_chatgpt):
    dossier = "Source : fil Gmail 19f6ae83afcd0922, dernier e-mail du 05/11. " * 12
    with pytest.raises(ErreurMetier, match="imprimées sur la fiche"):
        creer_fiche(session, acteur_chatgpt, notes_salle=dossier)
    fiche, _ = creer_fiche(session, acteur_admin, nom_client="Site", notes_salle=dossier,
                           lignes=[{"type": "plat", "libelle": "Steak", "quantite": 2, "commentaire": "x" * 200}])
    # ChatGPT peut encore ajouter une ligne : les notes et commentaires saisis sur le site ne le bloquent pas.
    fiches.ajouter_ligne(session, acteur_chatgpt, fiche.id, {"type": "dessert", "libelle": "Tiramisu", "quantite": 2})

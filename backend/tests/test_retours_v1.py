"""Règles décidées sur l'ancienne version (Albert Mail), reprises dans la v2."""
import pytest

from albert.domain.erreurs import ErreurMetier
from albert.services import fiches

from .test_fiches_devis import creer_fiche


def test_champ_inconnu_refuse_rien_n_est_modifie(session, acteur_admin):
    # Ancienne version : « status » ignoré en silence, la réponse annonçait une réussite.
    with pytest.raises(ErreurMetier, match="inconnu"):
        creer_fiche(session, acteur_admin, status="confirmed")
    fiche, _ = creer_fiche(session, acteur_admin, nom_client="Martin", couverts=10)
    with pytest.raises(ErreurMetier, match="inconnu"):
        fiches.modifier(session, acteur_admin, fiche.id, {"couverts": 12, "statut_resa": "x"})
    with pytest.raises(ErreurMetier, match="ligne inconnu"):
        fiches.modifier(session, acteur_admin, fiche.id, {"lignes": [{"type": "plat", "libelle": "Steak", "quantity": 2}]})
    assert fiches.obtenir(session, fiche.id).couverts == 10
    with pytest.raises(ErreurMetier, match="action dédiée"):
        fiches.modifier(session, acteur_admin, fiche.id, {"statut": "confirmee"})


def test_formule_avec_plats_refusee_pour_chatgpt_seulement(session, acteur_admin, acteur_chatgpt):
    lignes = [{"type": "plat", "libelle": "Steak", "quantite": 5}]
    with pytest.raises(ErreurMetier, match="plats prévalent"):
        creer_fiche(session, acteur_chatgpt, formule_repas="3 services", lignes=lignes)
    # Le site garde la règle du formulaire : les plats prévalent, la formule est vidée.
    fiche, _ = creer_fiche(session, acteur_admin, nom_client="Site", formule_repas="3 services", lignes=lignes)
    assert fiche.formule_repas is None and len(fiche.lignes) == 1


def test_chatgpt_confirme_avec_preuve_puis_finalise_et_rouvre(session, acteur_admin, acteur_chatgpt):
    fiche, _ = creer_fiche(session, acteur_admin, couverts=37)
    with pytest.raises(ErreurMetier):
        fiches.changer_statut(session, acteur_chatgpt, fiche.id, "confirmee")  # sans preuve
    fiches.changer_statut(session, acteur_chatgpt, fiche.id, "confirmee", motif="e-mail de la cliente du 05/11")
    assert fiches.obtenir(session, fiche.id).statut == "confirmee"  # sans plats : permis
    with pytest.raises(ErreurMetier, match="finaliser"):
        fiches.changer_statut(session, acteur_chatgpt, fiche.id, "finale")
    fiches.modifier(session, acteur_chatgpt, fiche.id, {"lignes": [{"type": "plat", "libelle": "Steak", "quantite": 37}]})
    fiches.changer_statut(session, acteur_chatgpt, fiche.id, "finale")
    with pytest.raises(ErreurMetier):
        fiches.modifier(session, acteur_chatgpt, fiche.id, {"couverts": 36})  # finale : figée
    fiches.changer_statut(session, acteur_chatgpt, fiche.id, "confirmee")  # rouvrir
    fiches.modifier(session, acteur_chatgpt, fiche.id, {"couverts": 38})
    with pytest.raises(ErreurMetier, match="dans l'outil"):
        fiches.changer_statut(session, acteur_chatgpt, fiche.id, "annulee", motif="test")

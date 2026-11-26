"""Contrôle des fiches à venir."""
from datetime import timedelta

from albert.models import Produit
from albert.services import controle

from .test_fiches_devis import creer_fiche

DANS_UN_MOIS = (controle.aujourd_hui() + timedelta(days=30)).isoformat()


def _problemes(http, nom):
    r = http.get("/api/fiches/controle")
    assert r.status_code == 200, r.text
    fiche = next((f for f in r.json()["fiches"] if f["client"] == nom), None)
    return [p["message"] for p in fiche["problemes"]] if fiche else []


def test_controle_signale_ce_qui_est_a_corriger(session, acteur_admin, acteur_chatgpt, http_admin):
    session.add(Produit(nom="Poule faisane à la brabançonne", categorie="plat", unite="piece", prix_centimes=2800))
    session.add(Produit(nom="Velouté d'hiver", categorie="entree", unite="piece", prix_centimes=None))
    session.commit()
    creer_fiche(session, acteur_admin, nom_client="Mme Dupont", date=DANS_UN_MOIS, couverts=20, lignes=[
        {"type": "plat", "libelle": "Poule faisane à la brabançonne", "quantite": 12},
        {"type": "plat", "libelle": "Poule faisane à la brabançonne — sans gluten", "quantite": 3},
        {"type": "plat", "libelle": "Alternative végétarienne (à valider)", "quantite": 3,
         "commentaire": "Préparation standard."},
        {"type": "entree", "libelle": "Velouté d'hiver", "quantite": 20},
        {"type": "dessert", "libelle": "Gâteau inventé", "quantite": 20},
    ], notes_salle="Vu dans le fil Gmail du 05/11")
    messages = _problemes(http_admin, "Mme Dupont")
    texte = "\n".join(messages)
    assert "18 plat(s) pour 20 couverts." in messages
    assert "« Alternative végétarienne (à valider) » : alternative à faire choisir par le chef." in messages
    assert "commentaire inutile" in texte
    assert "« Gâteau inventé » : hors carte." in messages
    assert "« Velouté d'hiver » : prix manquant (menu Carte ou Prix)." in messages
    assert "Notes salle : source Gmail" in texte
    assert "Nom du client" in texte
    assert "sans gluten" not in texte  # une variante d'un plat de la carte est correcte


def test_fiche_bien_faite_et_sharing_sans_remarque(session, acteur_admin, http_admin):
    creer_fiche(session, acteur_admin, nom_client="Deloitte", date=DANS_UN_MOIS, formule_repas="Sharing")
    resultat = http_admin.get("/api/fiches/controle").json()
    assert resultat["controlees"] >= 1
    assert all(f["client"] != "Deloitte" for f in resultat["fiches"])
    assert controle.A_CORRIGER == "a_corriger"

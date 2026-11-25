"""Menu Prix : ajouter une liste de plats (repris de l'« ajout en masse » de l'ancienne version)."""
import io

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import select

from albert.domain.erreurs import ErreurMetier
from albert.domain.import_carte import lire_liste, texte_depuis_fichier
from albert.models import Audit, Produit
from albert.services import catalogue

CARTE = """
ENTRÉES
Carpaccio de bœuf ........... 14,50 €
Croquettes aux crevettes 16.00
- Velouté du moment   € 9

Plats :
Steak frites, sauce au poivre ……… 26 €
Tartare 200 g
Cuvée du patron 2019
Burger maison 19
Bœuf 300g 24 €

— Desserts —
Moelleux au chocolat 9,5
Dame blanche | dessert | 8,00

Planche apéro | supplément | 6,50
Coupe de cava | supplément
"""


def _lu(texte, defaut=None):
    return [(l.nom, l.categorie, l.prix_centimes, l.erreur) for l in lire_liste(texte, defaut)]


def test_carte_copiee_telle_quelle():
    assert _lu(CARTE) == [
        ("Carpaccio de bœuf", "entree", 1450, None),
        ("Croquettes aux crevettes", "entree", 1600, None),
        ("Velouté du moment", "entree", 900, None),
        ("Steak frites, sauce au poivre", "plat", 2600, None),
        ("Tartare 200 g", "plat", None, None),   # « 200 g » n'est pas un prix
        ("Cuvée du patron 2019", "plat", None, None),  # une année n'est pas un prix
        ("Burger maison", "plat", 1900, None),   # un entier en fin de ligne est le prix
        ("Bœuf 300g", "plat", 2400, None),
        ("Moelleux au chocolat", "dessert", 950, None),
        ("Dame blanche", "dessert", 800, None),
        ("Planche apéro", "supplement", 650, None),
        ("Coupe de cava", "supplement", None, None),
    ]


def test_format_de_l_ancienne_version_et_type_par_defaut():
    # « Nom | type » comme dans l'ancienne version ; sans type, le type par défaut.
    assert _lu("Salade César | entrée\nBœuf bourguignon | plat\nCarpaccio", "plat") == [
        ("Salade César", "entree", None, None), ("Bœuf bourguignon", "plat", None, None),
        ("Carpaccio", "plat", None, None)]
    # Colonnes collées depuis un tableur (tabulations), type en anglais.
    assert _lu("Soup of the day\tstarter\t8,50") == [("Soup of the day", "entree", 850, None)]


def test_lignes_refusees_avec_la_raison():
    lues = lire_liste("Carpaccio\nSalade | entrée | quatorze\nTiramisu | dessert\ntiramisu | dessert\n| plat", None)
    assert [l.numero for l in lues] == [1, 2, 3, 4, 5]
    assert "Type inconnu" in lues[0].erreur
    assert "ni un type" in lues[1].erreur
    assert lues[2].erreur is None and "En double" in lues[3].erreur and "ligne 3" in lues[3].erreur
    assert lues[4].erreur == "Nom manquant."
    with pytest.raises(ErreurMetier):
        lire_liste("x", "formule_repas")  # pas de formule ni de privatisation par liste


def test_fichiers_texte_csv_et_pdf():
    csv = "Nom;Type;Prix\nCarpaccio;entrée;14,50\nTiramisu;dessert;\n".encode("cp1252")
    assert texte_depuis_fichier("carte.csv", csv) == "Carpaccio | entrée | 14,50\nTiramisu | dessert"
    tampon = io.BytesIO()
    page = canvas.Canvas(tampon)
    page.drawString(72, 760, "Desserts")
    page.drawString(72, 740, "Tiramisu maison ........ 9,00 €")
    page.save()
    assert _lu(texte_depuis_fichier("carte.pdf", tampon.getvalue())) == [("Tiramisu maison", "dessert", 900, None)]
    with pytest.raises(ErreurMetier):
        texte_depuis_fichier("carte.pdf", b"%PDF-1.4 abime")


def _produit(session, nom, categorie, prix, actif=True):
    p = Produit(nom=nom, categorie=categorie, unite="piece", prix_centimes=prix, actif=actif)
    session.add(p)
    session.commit()
    return p


def test_apercu_puis_import(session, acteur_admin):
    _produit(session, "Carpaccio de bœuf", "entree", None)        # prix manquant → complété
    _produit(session, "Steak frites, sauce au poivre", "plat", 2400)  # prix différent → gardé
    _produit(session, "Moelleux au chocolat", "dessert", 950, actif=False)  # désactivé → réactivé
    _produit(session, "Dame blanche", "plat", 800)                  # même nom, autre catégorie
    texte = CARTE + "\nSalade | entrée | quatorze"
    avant = len(list(session.scalars(select(Produit))))

    apercu = catalogue.analyser_liste(session, texte)
    actions = {l["nom"]: l["action"] for l in apercu}
    assert actions["Carpaccio de bœuf"] == "completer_prix"
    assert actions["Steak frites, sauce au poivre"] == "prix_different"
    assert actions["Moelleux au chocolat"] == "reactiver"
    assert actions["Croquettes aux crevettes"] == "creer"
    # Catalogue de départ : planche apéro sans prix (complété), coupe de cava à 6 € (rien à faire).
    assert actions["Planche apéro"] == "completer_prix"
    assert actions["Coupe de cava"] == "inchange"
    dame = next(l for l in apercu if l["nom"] == "Dame blanche")
    assert dame["action"] == "creer" and "plats" in dame["message"].lower()
    assert next(l for l in apercu if l["texte"].startswith("Salade"))["action"] == "erreur"
    assert len(list(session.scalars(select(Produit)))) == avant  # l'aperçu n'écrit rien

    lignes = catalogue.importer_liste(session, acteur_admin, texte)
    resume = catalogue.resume_liste(lignes)
    assert resume["erreur"] == 1 and resume["prix_different"] == 1
    assert len(list(session.scalars(select(Produit)))) == avant + resume["creer"]

    par_nom = {(p.categorie, p.nom): p for p in session.scalars(select(Produit))}
    assert par_nom[("entree", "Carpaccio de bœuf")].prix_centimes == 1450
    assert par_nom[("plat", "Steak frites, sauce au poivre")].prix_centimes == 2400  # gardé
    assert par_nom[("dessert", "Moelleux au chocolat")].actif is True
    assert par_nom[("entree", "Croquettes aux crevettes")].prix_centimes == 1600
    assert par_nom[("plat", "Tartare 200 g")].prix_centimes is None  # prix à compléter
    journal = [a.resume for a in session.scalars(select(Audit).where(Audit.action == "produit.importer"))]
    assert len(journal) == 1 and "1 ligne(s) ignorée(s)" in journal[0]

    # Relancer la même liste ne crée rien de plus.
    with pytest.raises(ErreurMetier) as e:
        catalogue.importer_liste(session, acteur_admin, CARTE)
    assert "Rien à importer" in e.value.message

    # Remplacer les prix seulement si on le demande.
    catalogue.importer_liste(session, acteur_admin, "Steak frites, sauce au poivre | plat | 26", remplacer_prix=True)
    session.refresh(par_nom[("plat", "Steak frites, sauce au poivre")])
    assert par_nom[("plat", "Steak frites, sauce au poivre")].prix_centimes == 2600


def test_droits(session, acteur_chatgpt, http_equipe):
    with pytest.raises(ErreurMetier):
        catalogue.importer_liste(session, acteur_chatgpt, "Carpaccio | entrée | 14")
    assert http_equipe.post("/api/produits/liste/apercu", json={"texte": "Carpaccio | entrée"}).status_code == 403
    assert http_equipe.post("/api/produits/liste", json={"texte": "Carpaccio | entrée"}).status_code == 403


def test_api(session, http_admin):
    r = http_admin.post("/api/produits/liste/apercu", json={"texte": "Carpaccio\nTiramisu | 9", "categorie_defaut": "dessert"})
    assert r.status_code == 200, r.text
    assert [l["action"] for l in r.json()["lignes"]] == ["creer", "creer"]
    assert session.scalars(select(Produit).where(Produit.nom == "Tiramisu")).first() is None
    r = http_admin.post("/api/produits/liste", json={"texte": "Carpaccio\nTiramisu | 9", "categorie_defaut": "dessert"})
    assert r.json()["resume"]["creer"] == 2
    assert session.scalars(select(Produit).where(Produit.nom == "Tiramisu")).one().prix_centimes == 900
    r = http_admin.post("/api/produits/liste/fichier", files={"fichier": ("carte.txt", "Entrées\nSoupe 7,50".encode(), "text/plain")})
    assert r.json() == {"texte": "Entrées\nSoupe 7,50"}
    assert http_admin.post("/api/produits/liste/apercu", json={"texte": " "}).status_code == 422


def test_nouvelle_carte_met_de_cote_tous_les_absents(session, acteur_admin):
    ancien = _produit(session, "Velouté d'automne", "entree", 900)
    garde = _produit(session, "Carpaccio de bœuf", "entree", 1450)
    plat = _produit(session, "Civet de chevreuil", "plat", 2800)  # aucun plat dans la liste : mis de côté aussi
    texte = "Entrées\nCarpaccio de bœuf 14,50\nSoupe de potiron 8,00"

    apercu = catalogue.analyser_liste(session, texte, nouvelle_carte=True)
    retires = [l["nom"] for l in apercu if l["action"] == "desactiver"]
    assert {"Velouté d'automne", "Civet de chevreuil"} <= set(retires) and "Carpaccio de bœuf" not in retires
    assert catalogue.analyser_liste(session, texte) == [l for l in apercu if l["action"] != "desactiver"]

    catalogue.importer_liste(session, acteur_admin, texte, nouvelle_carte=True)
    for p in (ancien, garde, plat):
        session.refresh(p)
    assert (ancien.actif, garde.actif, plat.actif) == (False, True, False)
    journal = session.scalars(select(Audit).where(Audit.action == "produit.importer")).one().resume
    assert f"{len(retires)} mis de côté" in journal

    # Une ligne illisible bloque le remplacement : elle pourrait être un plat à garder.
    with pytest.raises(ErreurMetier) as e:
        catalogue.importer_liste(session, acteur_admin, "Entrées\nSoupe | entrée | huit", nouvelle_carte=True)
    assert "corriger" in e.value.message
    session.refresh(garde)
    assert garde.actif is True


def test_supprimer_seulement_si_jamais_utilise(session, acteur_admin, http_admin):
    from albert.services import fiches

    from .conftest import nouveau_client

    faute = _produit(session, "Carpacio", "entree", 1450)
    servi = _produit(session, "Tiramisu", "dessert", 900)
    client = nouveau_client(session, acteur_admin)
    fiches.creer(session, acteur_admin, {"client_id": str(client.id), "date": "2030-06-12", "heure": "19:30",
                                         "couverts": 4, "lignes": [{"type": "dessert", "libelle": "Tiramisu", "quantite": 4}]})
    faute_id = faute.id
    assert http_admin.delete(f"/api/produits/{faute_id}").status_code == 200
    session.expire_all()  # supprimé par une autre session (celle de la requête)
    assert session.get(Produit, faute_id) is None
    r = http_admin.delete(f"/api/produits/{servi.id}")
    assert r.status_code == 422 and "mettre de côté" in r.json()["erreur"]["message"]
    # Un produit du catalogue de départ lié à une formule ne se supprime pas non plus.
    trois = session.scalars(select(Produit).where(Produit.nom == "3 services")).one()
    assert http_admin.delete(f"/api/produits/{trois.id}").status_code == 422


def test_mettre_toute_la_carte_de_cote_puis_la_reprendre(session, acteur_admin, http_admin):
    ancien = _produit(session, "Velouté d'automne", "entree", 900)
    plat = _produit(session, "Civet de chevreuil", "plat", None)
    r = http_admin.post("/api/produits/carte/mettre-de-cote")
    assert r.status_code == 200, r.text
    assert r.json()["nombre"] >= 2
    for p in (ancien, plat):
        session.refresh(p)
    assert (ancien.actif, plat.actif) == (False, False)
    assert plat not in catalogue.lister_produits(session, manquants=True)  # plus dans « Prix manquants »
    # Un ancien plat repris dans la nouvelle carte revient, avec son prix.
    lignes = catalogue.importer_liste(session, acteur_admin, "Entrées\nVelouté d'automne", nouvelle_carte=True)
    assert [l["action"] for l in lignes if l["nom"] == "Velouté d'automne"] == ["reactiver"]
    session.refresh(ancien)
    assert ancien.actif is True and ancien.prix_centimes == 900


def test_les_supplements_restent_quand_la_carte_change(session, acteur_admin, http_admin):
    planche = _produit(session, "Planche du chef", "supplement", 1800)
    plat = _produit(session, "Civet de chevreuil", "plat", 2800)
    lignes = catalogue.analyser_liste(session, "Entrées\nSoupe 8", nouvelle_carte=True)
    retires = {l["nom"] for l in lignes if l["action"] == "desactiver"}
    assert "Civet de chevreuil" in retires and "Planche du chef" not in retires
    catalogue.mettre_carte_de_cote(session, acteur_admin)
    session.refresh(planche)
    session.refresh(plat)
    assert (planche.actif, plat.actif) == (True, False)

    # Des suppléments mis de côté (ancienne règle) se remettent tous d'un coup.
    planche.actif = False
    session.commit()
    r = http_admin.post("/api/produits/carte/remettre", json={"categorie": "supplement"})
    assert r.status_code == 200 and r.json()["nombre"] >= 1
    session.refresh(planche)
    session.refresh(plat)
    assert (planche.actif, plat.actif) == (True, False)
    assert http_admin.post("/api/produits/carte/remettre", json={"categorie": "coupe"}).status_code == 422

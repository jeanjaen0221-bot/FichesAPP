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
Menu 3
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
        ("Menu 3", "plat", None, None),          # un entier nu n'est pas un prix
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

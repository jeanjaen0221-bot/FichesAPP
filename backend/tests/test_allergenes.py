"""Allergènes ajoutés dans Paramètres, et reprise des allergènes et de la liaison Gmail de l'ancienne version."""
import io

import pytest
from PIL import Image
from sqlalchemy import select, text

from albert.domain.erreurs import ErreurMetier
from albert.domain.normalisation import lire_allergenes
from albert.models import Allergene, ConnexionGmail, Fiche
from albert.pdf.documents import pdf_fiche
from albert.reprise import Rapport, reprendre
from albert.services import allergenes, catalogue, fiches
from albert.services.gmail import _chiffreur

from .conftest import nouveau_client
from .test_reprise import ancienne_base


def _png(couleur=(200, 0, 0, 255), taille=(40, 20)) -> bytes:
    sortie = io.BytesIO()
    Image.new("RGBA", taille, couleur).save(sortie, format="PNG")
    return sortie.getvalue()


def test_lecture_avec_allergenes_ajoutes():
    ajoutes = {"kiwi": "Kiwi", "fruits_rouges": "Fruits rouges"}
    assert lire_allergenes(["Kiwi", "allergie aux fruits rouges", "lactose"], ajoutes) == ["kiwi", "fruits_rouges", "lait"]
    with pytest.raises(ErreurMetier) as e:
        lire_allergenes(["kiwi"])
    assert "Paramètres" in e.value.message


def test_ajout_utilisation_et_suppression(session, acteur_admin):
    a = allergenes.creer(session, acteur_admin, "Kiwi", icone=_png())
    assert a.cle == "kiwi"
    with Image.open(io.BytesIO(a.icone)) as image:
        assert image.format == "PNG" and image.width == image.height  # icône carrée
    with pytest.raises(ErreurMetier):
        allergenes.creer(session, acteur_admin, "kiwi")
    with pytest.raises(ErreurMetier):
        allergenes.creer(session, acteur_admin, "Gluten")  # déjà réglementaire

    assert {"cle": "kiwi", "libelle": "Kiwi"} in catalogue.references(session)["allergenes"]
    client = nouveau_client(session, acteur_admin)
    fiche, _ = fiches.creer(session, acteur_admin, {"client_id": str(client.id), "date": "2030-06-12",
                                                    "heure": "19:30", "couverts": 4, "allergenes": ["KIWI", "gluten"]})
    assert fiche.allergenes == ["kiwi", "gluten"]

    with pytest.raises(ErreurMetier):
        allergenes.supprimer(session, acteur_admin, "kiwi")  # utilisé sur une fiche
    with pytest.raises(ErreurMetier):
        allergenes.supprimer(session, acteur_admin, "gluten")
    allergenes.creer(session, acteur_admin, "Fraise")
    allergenes.supprimer(session, acteur_admin, "fraise")
    assert session.get(Allergene, "fraise") is None


def test_chatgpt_ne_gere_pas_les_allergenes(session, acteur_chatgpt):
    with pytest.raises(ErreurMetier):
        allergenes.creer(session, acteur_chatgpt, "Kiwi")


def test_pdf_avec_allergene_ajoute(session, acteur_admin, http_admin):
    allergenes.creer(session, acteur_admin, "Kiwi", icone=_png())
    client = nouveau_client(session, acteur_admin)
    fiche, _ = fiches.creer(session, acteur_admin, {"client_id": str(client.id), "date": "2030-06-12",
                                                    "heure": "19:30", "couverts": 4, "allergenes": ["kiwi"]})
    r = http_admin.get(f"/api/fiches/{fiche.id}/pdf?variante=salle")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    # Le libellé et l'icône arrivent jusqu'au rendu.
    contenu = pdf_fiche({**fiches.fiche_dict(session, fiche), "libelles_allergenes": {"kiwi": "Kiwi"},
                         "icones_allergenes": allergenes.icones(session)}, "salle")
    assert contenu.startswith(b"%PDF")


def test_api_allergenes(session, http_admin, http_equipe):
    r = http_admin.post("/api/allergenes", data={"libelle": "Kiwi"}, files={"icone": ("kiwi.png", _png(), "image/png")})
    assert r.status_code == 201, r.text
    assert r.json() == {"cle": "kiwi", "libelle": "Kiwi", "icone": True}
    assert http_equipe.get("/api/allergenes").json() == [{"cle": "kiwi", "libelle": "Kiwi", "icone": True}]
    assert http_equipe.get("/api/allergenes/kiwi/icone").headers["content-type"] == "image/png"
    assert http_equipe.post("/api/allergenes", data={"libelle": "Fraise"}).status_code == 403
    r = http_admin.post("/api/allergenes/kiwi", data={"libelle": "Kiwi (et actinidia)", "retirer_icone": "true"})
    assert r.json() == {"cle": "kiwi", "libelle": "Kiwi (et actinidia)", "icone": False}
    assert http_admin.post("/api/allergenes", data={"libelle": "Fraise"},
                           files={"icone": ("f.png", b"pas une image", "image/png")}).status_code == 422
    assert http_admin.delete("/api/allergenes/kiwi").status_code == 200


def test_reprise_allergenes_et_gmail(session, tmp_path):
    source = ancienne_base(tmp_path / "ancienne.db")
    with source.begin() as c:
        c.execute(text("CREATE TABLE allergen (key TEXT, label TEXT, icon_bytes BLOB, updated_at DATETIME)"))
        c.execute(text("INSERT INTO allergen VALUES ('kiwi','Kiwi',:i,NULL),('gluten','Gluten',NULL,NULL),"
                       "('fraise','Fraise',:x,NULL)"), {"i": _png(), "x": b"illisible"})
        c.execute(text("CREATE TABLE gmailtoken (id INT, email TEXT, refresh_token TEXT, access_token TEXT, "
                       "access_token_expires_at DATETIME, updated_at DATETIME)"))
        c.execute(text("INSERT INTO gmailtoken VALUES (1,'info@albert.brussels','1//jeton-durable',NULL,NULL,NULL)"))
    rapport = Rapport()
    reprendre(source, session, rapport)
    session.commit()

    assert {a.cle: (a.libelle, a.icone is not None) for a in session.scalars(select(Allergene))} == {
        "kiwi": ("Kiwi", True), "fraise": ("Fraise", False)}
    assert any("Fraise" in r for r in rapport.remarques)
    # « kiwi » était parti dans les notes cuisine faute d'être connu : il est maintenant un allergène.
    volta = session.scalars(select(Fiche).where(Fiche.cle_idempotence == "reprise:r1")).one()
    assert volta.allergenes == ["lait", "kiwi"]
    assert "kiwi" not in (volta.notes_cuisine or "").lower()

    gmail = session.get(ConnexionGmail, 1)
    assert gmail.email == "info@albert.brussels" and gmail.relie_par == "reprise"
    assert _chiffreur().decrypt(gmail.jeton_chiffre.encode()).decode() == "1//jeton-durable"
    assert "1//jeton-durable" not in gmail.jeton_chiffre

    # Relancer ne crée rien de plus et ne remplace pas la boîte.
    reprendre(source, session, Rapport())
    session.commit()
    assert len(list(session.scalars(select(Allergene)))) == 2

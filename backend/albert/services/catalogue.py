"""Menus « Prix » (produits) et « Formules » (formules repas et boissons)."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.argent import format_euros, lire_euros
from ..domain.erreurs import ErreurMetier, introuvable
from ..domain.normalisation import cle, lire_allergenes, texte_court
from ..domain.regles import (
    CATEGORIES_PRODUIT,
    COMPORTEMENTS_FORMULE,
    ESPACES,
    LIBELLES_CATEGORIES,
    LIBELLES_STATUTS_FICHE,
    LIBELLES_UNITES,
    MODES_BOISSONS,
    UNITES,
)
from ..models import BonLigne, DevisLigne, Fiche, FicheLigne, FormuleBoissons, FormuleRepas, Produit
from . import allergenes as allergenes_service
from .contexte import Acteur, journaliser, lire_parametres

COULEURS_BOISSONS = ("bleu", "rouge", "cyan", "violet", "vert", "ambre", "indigo", "gris")


# --------------------------------------------------------------- produits

def produit_dict(p: Produit) -> dict[str, Any]:
    return {
        "id": str(p.id), "nom": p.nom, "categorie": p.categorie, "unite": p.unite,
        "unite_libelle": LIBELLES_UNITES.get(p.unite, p.unite),
        "prix_centimes": p.prix_centimes, "prix": format_euros(p.prix_centimes),
        "prix_manquant": p.prix_centimes is None, "allergenes": p.allergenes or [],
        "actif": p.actif, "ordre": p.ordre,
    }


def lister_produits(session: Session, categorie: Optional[str] = None, q: Optional[str] = None,
                    manquants: bool = False, actifs_seulement: bool = False) -> list[Produit]:
    stmt = select(Produit)
    if categorie:
        stmt = stmt.where(Produit.categorie == categorie)
    if manquants:
        stmt = stmt.where(Produit.prix_centimes.is_(None), Produit.actif.is_(True))
    if actifs_seulement:
        stmt = stmt.where(Produit.actif.is_(True))
    produits = list(session.scalars(stmt.order_by(Produit.categorie, Produit.ordre, Produit.nom)))
    if q:
        mots = cle(q).split()
        produits = [p for p in produits if all(m in cle(p.nom) for m in mots)]
    return produits


def compter_prix_manquants(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(Produit).where(Produit.prix_centimes.is_(None), Produit.actif.is_(True))
    ) or 0


def _valider_produit(session: Session, donnees: dict[str, Any], partiel: bool) -> dict[str, Any]:
    sortie: dict[str, Any] = {}
    if "nom" in donnees or not partiel:
        sortie["nom"] = texte_court(donnees.get("nom"), "nom", 200, obligatoire=True)
    if "categorie" in donnees or not partiel:
        c = donnees.get("categorie")
        if c not in CATEGORIES_PRODUIT:
            raise ErreurMetier("valeur_non_permise", f"Catégorie inconnue : {c!r}.", champ="categorie",
                               valeurs_permises=list(CATEGORIES_PRODUIT))
        sortie["categorie"] = c
    if "unite" in donnees or not partiel:
        u = donnees.get("unite") or "piece"
        if u not in UNITES:
            raise ErreurMetier("valeur_non_permise", f"Unité inconnue : {u!r}.", champ="unite",
                               valeurs_permises=list(UNITES))
        sortie["unite"] = u
    if "prix" in donnees:
        sortie["prix_centimes"] = lire_euros(donnees["prix"])
    elif "prix_centimes" in donnees:
        sortie["prix_centimes"] = lire_euros(donnees["prix_centimes"]) if donnees["prix_centimes"] is not None else None
    if "allergenes" in donnees:
        sortie["allergenes"] = lire_allergenes(donnees["allergenes"], allergenes_service.supplementaires(session))
    for champ in ("actif",):
        if champ in donnees:
            sortie[champ] = bool(donnees[champ])
    if "ordre" in donnees:
        sortie["ordre"] = int(donnees["ordre"] or 0)
    return sortie


def _doublon_produit(session: Session, categorie: str, nom: str, sauf: Optional[uuid.UUID] = None) -> None:
    for p in session.scalars(select(Produit).where(Produit.categorie == categorie)):
        if p.id != sauf and cle(p.nom) == cle(nom):
            raise ErreurMetier("doublon_probable", f"« {p.nom} » existe déjà dans {LIBELLES_CATEGORIES[categorie]}.",
                               champ="nom", details={"produit_id": str(p.id)})


def creer_produit(session: Session, acteur: Acteur, donnees: dict[str, Any]) -> Produit:
    acteur.exiger("prix")
    valeurs = _valider_produit(session, donnees, partiel=False)
    _doublon_produit(session, valeurs["categorie"], valeurs["nom"])
    produit = Produit(**valeurs)
    session.add(produit)
    session.flush()
    journaliser(session, acteur, "produit.creer", "produit", produit.id,
                f"{produit.nom} ({format_euros(produit.prix_centimes)})", None, produit_dict(produit))
    session.commit()
    return produit


def modifier_produit(session: Session, acteur: Acteur, produit_id: uuid.UUID, donnees: dict[str, Any]) -> Produit:
    acteur.exiger("prix")
    produit = session.get(Produit, produit_id)
    if produit is None:
        raise introuvable("Produit")
    avant = produit_dict(produit)
    valeurs = _valider_produit(session, donnees, partiel=True)
    if "nom" in valeurs or "categorie" in valeurs:
        _doublon_produit(session, valeurs.get("categorie", produit.categorie), valeurs.get("nom", produit.nom), produit.id)
    for k, v in valeurs.items():
        setattr(produit, k, v)
    session.flush()
    resume = produit.nom
    if avant["prix_centimes"] != produit.prix_centimes:
        resume += f" : {avant['prix']} → {format_euros(produit.prix_centimes)}"
    journaliser(session, acteur, "produit.modifier", "produit", produit.id, resume, avant, produit_dict(produit))
    session.commit()
    return produit


def produit_utilise(session: Session, produit_id: uuid.UUID) -> Optional[str]:
    """Où le produit sert déjà (fiche, devis, bon, formule), ou None s'il n'a jamais servi."""
    usages = (
        (FicheLigne.produit_id, "une fiche"), (Fiche.privatisation_id, "une fiche"),
        (DevisLigne.produit_id, "un devis"), (BonLigne.produit_id, "un bon pour facturation"),
        (FormuleRepas.produit_id, "une formule repas"), (FormuleBoissons.base_produit_id, "une formule boissons"),
        (FormuleBoissons.coupe_produit_id, "une formule boissons"),
    )
    for colonne, ou in usages:
        if session.scalar(select(func.count()).select_from(colonne.class_).where(colonne == produit_id)):
            return ou
    return None


def supprimer_produit(session: Session, acteur: Acteur, produit_id: uuid.UUID) -> None:
    """Seulement un produit qui n'a jamais servi (faute de frappe, ajout en trop) ; sinon on le retire
    de la carte (désactivé) : les fiches, devis et bons qui l'ont gardent leur libellé et leur prix."""
    acteur.exiger("prix")
    produit = session.get(Produit, produit_id)
    if produit is None:
        raise introuvable("Produit")
    ou = produit_utilise(session, produit.id)
    if ou:
        raise ErreurMetier("regle_metier", f"« {produit.nom} » est déjà utilisé dans {ou} : il ne peut pas être "
                                           "supprimé. Le mettre de côté à la place : il quitte la carte sans être effacé.")
    avant = produit_dict(produit)
    session.delete(produit)
    journaliser(session, acteur, "produit.supprimer", "produit", produit.id, f"{produit.nom} supprimé", avant, None)
    session.commit()


# --------------------------------------------------------------- ajouter une liste (import)

# Ce que fera l'import pour chaque ligne. Le même calcul sert à l'aperçu et à l'import :
# l'équipe importe exactement ce qu'elle a vu (le texte est relu par le serveur, jamais l'aperçu).
ACTIONS_IMPORT = {
    "creer": "Nouveau",
    "completer_prix": "Prix ajouté",
    "remplacer_prix": "Prix remplacé",
    "reactiver": "Réactivé",
    "inchange": "Déjà sur la carte",
    "prix_different": "Prix différent (gardé)",
    "erreur": "Ignoré",
    "desactiver": "Mis de côté",
}
# Quand la carte change, elle change entièrement… sauf les suppléments, qui restent.
CATEGORIES_CHANGEANT_AVEC_LA_CARTE = ("entree", "plat", "dessert")
ACTIONS_ECRITURE = ("creer", "completer_prix", "remplacer_prix", "reactiver", "desactiver")


def analyser_liste(session: Session, texte: str, categorie_defaut: Optional[str] = None,
                   remplacer_prix: bool = False, nouvelle_carte: bool = False) -> list[dict[str, Any]]:
    """Ce que fera l'import, ligne par ligne.

    `nouvelle_carte` : la liste remplace la carte. Les entrées, plats et desserts absents de la
    liste sont mis de côté (désactivés) ; ceux qui y figurent restent ou reviennent sur la carte.
    Les suppléments ne changent pas avec la carte : ils restent tous.
    """
    from ..domain.import_carte import lire_liste

    existants: dict[tuple[str, str], Produit] = {
        (p.categorie, cle(p.nom)): p
        for p in session.scalars(select(Produit).where(Produit.categorie.in_(("entree", "plat", "dessert", "supplement"))))
    }
    par_nom: dict[str, list[Produit]] = {}
    for (_, k), p in existants.items():
        par_nom.setdefault(k, []).append(p)
    sortie = []
    for lue in lire_liste(texte, categorie_defaut or None):
        ligne: dict[str, Any] = {
            "numero": lue.numero, "texte": lue.texte, "nom": lue.nom, "categorie": lue.categorie,
            "prix_centimes": lue.prix_centimes, "prix": format_euros(lue.prix_centimes) if lue.prix_centimes is not None else None,
            "produit_id": None, "prix_actuel": None, "message": lue.erreur,
        }
        if lue.erreur:
            ligne["action"] = "erreur"
        else:
            p = existants.get((lue.categorie, cle(lue.nom)))  # type: ignore[arg-type]
            if p is None:
                ligne["action"] = "creer"
                ailleurs = [LIBELLES_CATEGORIES[q.categorie].lower() for q in par_nom.get(cle(lue.nom), [])]
                messages = ["Prix à compléter."] if lue.prix_centimes is None else []
                if ailleurs:
                    messages.append(f"Existe déjà dans : {', '.join(ailleurs)}. Vérifier le type.")
                ligne["message"] = " ".join(messages) or None
            else:
                ligne.update(produit_id=str(p.id), nom=p.nom, prix_actuel=format_euros(p.prix_centimes))
                nouveau_prix = lue.prix_centimes is not None and lue.prix_centimes != p.prix_centimes
                if nouveau_prix and p.prix_centimes is None:
                    ligne["action"] = "completer_prix"
                elif nouveau_prix and remplacer_prix:
                    ligne["action"] = "remplacer_prix"
                elif not p.actif:
                    ligne["action"] = "reactiver"
                    if nouveau_prix:
                        ligne["message"] = f"Prix gardé : {format_euros(p.prix_centimes)}."
                elif nouveau_prix:
                    ligne["action"] = "prix_different"
                    ligne["message"] = (f"Le menu Prix dit {format_euros(p.prix_centimes)} : prix gardé "
                                        "(cocher « remplacer les prix » pour prendre celui de la liste).")
                else:
                    ligne["action"] = "inchange"
                if not p.actif and ligne["action"] in ("completer_prix", "remplacer_prix"):
                    ligne["message"] = "Produit désactivé : il sera réactivé."
        ligne["action_libelle"] = ACTIONS_IMPORT[ligne["action"]]
        sortie.append(ligne)
    if nouvelle_carte:
        presents = {(l["categorie"], cle(l["nom"])) for l in sortie if l["action"] != "erreur"}
        for (categorie, k), p in sorted(existants.items(), key=lambda e: (e[0][0], e[1].ordre, e[1].nom)):
            if categorie in CATEGORIES_CHANGEANT_AVEC_LA_CARTE and p.actif and (categorie, k) not in presents:
                sortie.append({
                    "numero": None, "texte": "", "nom": p.nom, "categorie": categorie, "prix_centimes": p.prix_centimes,
                    "prix": None, "produit_id": str(p.id), "prix_actuel": format_euros(p.prix_centimes),
                    "action": "desactiver", "action_libelle": ACTIONS_IMPORT["desactiver"],
                    "message": "Absent de la nouvelle carte : mis de côté. Les fiches et devis qui l'ont le gardent.",
                })
    return sortie


def mettre_carte_de_cote(session: Session, acteur: Acteur) -> int:
    """Met de côté (désactive) les entrées, plats et desserts. Les suppléments restent.

    Rien n'est supprimé : chacun peut être remis.
    """
    acteur.exiger("prix")
    produits = list(session.scalars(select(Produit).where(
        Produit.categorie.in_(CATEGORIES_CHANGEANT_AVEC_LA_CARTE), Produit.actif.is_(True))))
    for p in produits:
        p.actif = False
    session.flush()
    journaliser(session, acteur, "produit.modifier", "produit", None,
                f"Toute la carte mise de côté : {len(produits)} produit(s)")
    session.commit()
    return len(produits)


def remettre_sur_la_carte(session: Session, acteur: Acteur, categorie: str) -> int:
    """Remet sur la carte tous les produits mis de côté d'un type (ex. tous les suppléments)."""
    acteur.exiger("prix")
    if categorie not in ("entree", "plat", "dessert", "supplement"):
        raise ErreurMetier("valeur_non_permise", "Type inconnu.", champ="categorie",
                           valeurs_permises=["entree", "plat", "dessert", "supplement"])
    produits = list(session.scalars(select(Produit).where(Produit.categorie == categorie, Produit.actif.is_(False))))
    for p in produits:
        p.actif = True
    session.flush()
    journaliser(session, acteur, "produit.modifier", "produit", None,
                f"{LIBELLES_CATEGORIES[categorie]} remis sur la carte : {len(produits)} produit(s)")
    session.commit()
    return len(produits)


def resume_liste(lignes: list[dict[str, Any]]) -> dict[str, int]:
    return {action: sum(1 for l in lignes if l["action"] == action) for action in ACTIONS_IMPORT}


def importer_liste(session: Session, acteur: Acteur, texte: str, categorie_defaut: Optional[str] = None,
                   remplacer_prix: bool = False, nouvelle_carte: bool = False) -> list[dict[str, Any]]:
    """Crée les nouveaux produits, complète ou remplace les prix, réactive. Tout ou rien.

    Un produit existant n'est jamais renommé ni changé de catégorie, et son prix n'est remplacé
    que si on le demande. Les lignes refusées sont ignorées (elles restent dans le rapport).
    """
    acteur.exiger("prix")
    lignes = analyser_liste(session, texte, categorie_defaut, remplacer_prix, nouvelle_carte)
    if nouvelle_carte and any(l["action"] == "erreur" for l in lignes):
        # Une ligne illisible pourrait être un plat qu'on garde : on ne retire rien tant qu'elle n'est pas corrigée.
        raise ErreurMetier("regle_metier", "Des lignes sont ignorées : les corriger (ou les effacer) avant de "
                                           "remplacer la carte, pour ne retirer aucun plat par erreur.", champ="texte")
    a_faire = [l for l in lignes if l["action"] in ACTIONS_ECRITURE]
    if not a_faire:
        raise ErreurMetier("regle_metier", "Rien à importer : tous les produits sont déjà sur la carte "
                                           "ou les lignes sont refusées.", champ="texte")
    ordre = (session.scalar(select(func.max(Produit.ordre))) or 0) + 1
    for l in a_faire:
        if l["action"] == "creer":
            p = Produit(nom=l["nom"], categorie=l["categorie"], unite="piece", prix_centimes=l["prix_centimes"],
                        actif=True, ordre=ordre)
            ordre += 1
            session.add(p)
            session.flush()
            l["produit_id"] = str(p.id)
            journaliser(session, acteur, "produit.creer", "produit", p.id,
                        f"{p.nom} ({format_euros(p.prix_centimes)}) — ajouté par liste", None, produit_dict(p))
            continue
        p = session.get(Produit, uuid.UUID(l["produit_id"]))
        avant = produit_dict(p)
        if l["action"] == "desactiver":
            p.actif = False
            session.flush()
            journaliser(session, acteur, "produit.modifier", "produit", p.id, f"{p.nom} mis de côté — nouvelle carte",
                        avant, produit_dict(p))
            continue
        if l["action"] in ("completer_prix", "remplacer_prix"):
            p.prix_centimes = l["prix_centimes"]
        p.actif = True
        session.flush()
        resume = p.nom
        if avant["prix_centimes"] != p.prix_centimes:
            resume += f" : {avant['prix']} → {format_euros(p.prix_centimes)}"
        if not avant["actif"]:
            resume += " (réactivé)"
        journaliser(session, acteur, "produit.modifier", "produit", p.id, resume + " — liste", avant, produit_dict(p))
    compte = resume_liste(lignes)
    journaliser(session, acteur, "produit.importer", "produit", None,
                f"Liste importée dans le menu Prix : {compte['creer']} nouveau(x), "
                f"{compte['completer_prix'] + compte['remplacer_prix']} prix, {compte['reactiver']} réactivé(s), "
                f"{compte['erreur']} ligne(s) ignorée(s)"
                + (f", {compte['desactiver']} mis de côté" if nouvelle_carte else ""))
    session.commit()
    return lignes


# --------------------------------------------------------------- formules

def formule_repas_dict(f: FormuleRepas) -> dict[str, Any]:
    if f.comportement == "carte":
        prix = "prix de la carte"
        centimes = None
    else:
        centimes = f.produit.prix_centimes if f.produit else None
        prix = format_euros(centimes) + " par personne" if centimes is not None else "prix manquant"
    return {
        "id": str(f.id), "nom": f.nom, "comportement": f.comportement, "nb_services": f.nb_services,
        "produit_id": str(f.produit_id) if f.produit_id else None, "prix_centimes": centimes,
        "prix": prix, "actif": f.actif, "ordre": f.ordre,
    }


def formule_boissons_dict(f: FormuleBoissons) -> dict[str, Any]:
    parts = [p for p in (f.base_produit, f.coupe_produit) if p is not None]
    if f.mode != "formule":
        centimes, prix = None, ("à la consommation" if f.mode == "consommation" else "aucune ligne")
    elif any(p.prix_centimes is None for p in parts):
        centimes, prix = None, "prix manquant"
    else:
        centimes = sum(p.prix_centimes for p in parts)  # type: ignore[misc]
        detail = " + ".join(format_euros(p.prix_centimes) for p in parts)
        prix = f"{format_euros(centimes)} par personne" + (f" ({detail})" if len(parts) > 1 else "")
    return {
        "id": str(f.id), "nom": f.nom, "mode": f.mode,
        "base_produit_id": str(f.base_produit_id) if f.base_produit_id else None,
        "coupe_produit_id": str(f.coupe_produit_id) if f.coupe_produit_id else None,
        "base": f.base_produit.nom if f.base_produit else None,
        "coupe": f.coupe_produit.nom if f.coupe_produit else None,
        "prix_centimes": centimes, "prix": prix, "couleur": f.couleur, "par_defaut": f.par_defaut,
        "actif": f.actif, "ordre": f.ordre,
    }


def lister_formules_repas(session: Session, actives: bool = False) -> list[FormuleRepas]:
    stmt = select(FormuleRepas).order_by(FormuleRepas.ordre, FormuleRepas.nom)
    if actives:
        stmt = stmt.where(FormuleRepas.actif.is_(True))
    return list(session.scalars(stmt))


def lister_formules_boissons(session: Session, actives: bool = False) -> list[FormuleBoissons]:
    stmt = select(FormuleBoissons).order_by(FormuleBoissons.ordre, FormuleBoissons.nom)
    if actives:
        stmt = stmt.where(FormuleBoissons.actif.is_(True))
    return list(session.scalars(stmt))


def formules_par_services(session: Session) -> dict[int, FormuleRepas]:
    sortie: dict[int, FormuleRepas] = {}
    for f in lister_formules_repas(session, actives=True):
        if f.comportement == "services" and f.nb_services and f.nb_services not in sortie:
            sortie[f.nb_services] = f
    return sortie


def _produit_de(session: Session, produit_id: Any, categories: tuple[str, ...], champ: str) -> Optional[Produit]:
    if produit_id in (None, ""):
        return None
    try:
        produit = session.get(Produit, uuid.UUID(str(produit_id)))
    except ValueError:
        produit = None
    if produit is None or produit.categorie not in categories:
        raise ErreurMetier("valeur_non_permise", f"{champ} : produit introuvable dans le menu Prix.", champ=champ)
    return produit


def enregistrer_formule_repas(session: Session, acteur: Acteur, donnees: dict[str, Any],
                              formule_id: Optional[uuid.UUID] = None) -> FormuleRepas:
    acteur.exiger("prix")
    formule = session.get(FormuleRepas, formule_id) if formule_id else FormuleRepas()
    if formule is None:
        raise introuvable("Formule")
    avant = formule_repas_dict(formule) if formule_id else None
    if "nom" in donnees or not formule_id:
        nom = texte_court(donnees.get("nom"), "nom", 100, obligatoire=True)
        for autre in lister_formules_repas(session):
            if autre.id != formule.id and cle(autre.nom) == cle(nom):
                raise ErreurMetier("doublon_probable", f"La formule « {autre.nom} » existe déjà.", champ="nom")
        formule.nom = nom
    if "comportement" in donnees or not formule_id:
        c = donnees.get("comportement")
        if c not in COMPORTEMENTS_FORMULE:
            raise ErreurMetier("valeur_non_permise", "Comportement inconnu.", champ="comportement",
                               valeurs_permises=list(COMPORTEMENTS_FORMULE))
        formule.comportement = c
    if "nb_services" in donnees:
        n = donnees.get("nb_services")
        formule.nb_services = int(n) if n not in (None, "") else None
    if formule.comportement == "services" and formule.nb_services not in (1, 2, 3):
        raise ErreurMetier("regle_metier", "Une formule « services » indique 1, 2 ou 3 services.", champ="nb_services")
    if formule.comportement != "services":
        formule.nb_services = None
    if "produit_id" in donnees:
        produit = _produit_de(session, donnees.get("produit_id"), ("formule_repas",), "produit_id")
        formule.produit_id = produit.id if produit else None
    if formule.comportement == "carte":
        formule.produit_id = None
    elif formule.produit_id is None:
        # Crée le produit correspondant dans le menu Prix (prix à compléter).
        existant = next((p for p in lister_produits(session, "formule_repas") if cle(p.nom) == cle(formule.nom)), None)
        if existant is None:
            existant = Produit(nom=formule.nom, categorie="formule_repas", unite="par_personne", prix_centimes=None)
            session.add(existant)
            session.flush()
        formule.produit_id = existant.id
    for champ in ("actif",):
        if champ in donnees:
            setattr(formule, champ, bool(donnees[champ]))
    if "ordre" in donnees:
        formule.ordre = int(donnees["ordre"] or 0)
    session.add(formule)
    session.flush()
    session.refresh(formule)
    journaliser(session, acteur, "formule_repas." + ("modifier" if formule_id else "creer"), "formule_repas",
                formule.id, formule.nom, avant, formule_repas_dict(formule))
    session.commit()
    return formule


def enregistrer_formule_boissons(session: Session, acteur: Acteur, donnees: dict[str, Any],
                                 formule_id: Optional[uuid.UUID] = None) -> FormuleBoissons:
    acteur.exiger("prix")
    formule = session.get(FormuleBoissons, formule_id) if formule_id else FormuleBoissons()
    if formule is None:
        raise introuvable("Formule")
    avant = formule_boissons_dict(formule) if formule_id else None
    if "nom" in donnees or not formule_id:
        nom = texte_court(donnees.get("nom"), "nom", 100, obligatoire=True)
        for autre in lister_formules_boissons(session):
            if autre.id != formule.id and cle(autre.nom) == cle(nom):
                raise ErreurMetier("doublon_probable", f"La formule « {autre.nom} » existe déjà.", champ="nom")
        formule.nom = nom
    if "mode" in donnees or not formule_id:
        m = donnees.get("mode") or "formule"
        if m not in MODES_BOISSONS:
            raise ErreurMetier("valeur_non_permise", "Mode inconnu.", champ="mode", valeurs_permises=list(MODES_BOISSONS))
        formule.mode = m
    if "base_produit_id" in donnees:
        p = _produit_de(session, donnees.get("base_produit_id"), ("formule_boissons",), "base_produit_id")
        formule.base_produit_id = p.id if p else None
    if "coupe_produit_id" in donnees:
        p = _produit_de(session, donnees.get("coupe_produit_id"), ("coupe",), "coupe_produit_id")
        formule.coupe_produit_id = p.id if p else None
    if formule.mode != "formule":
        formule.base_produit_id = None
        formule.coupe_produit_id = None
    elif formule.base_produit_id is None and formule.coupe_produit_id is None:
        raise ErreurMetier("regle_metier", "Une formule boissons a une base et/ou une coupe.", champ="base_produit_id")
    if "couleur" in donnees:
        if donnees["couleur"] not in COULEURS_BOISSONS:
            raise ErreurMetier("valeur_non_permise", "Couleur inconnue.", champ="couleur",
                               valeurs_permises=list(COULEURS_BOISSONS))
        formule.couleur = donnees["couleur"]
    if "actif" in donnees:
        formule.actif = bool(donnees["actif"])
    if "ordre" in donnees:
        formule.ordre = int(donnees["ordre"] or 0)
    if donnees.get("par_defaut"):
        for autre in lister_formules_boissons(session):
            autre.par_defaut = False
        formule.par_defaut = True
    session.add(formule)
    session.flush()
    session.refresh(formule)
    journaliser(session, acteur, "formule_boissons." + ("modifier" if formule_id else "creer"), "formule_boissons",
                formule.id, formule.nom, avant, formule_boissons_dict(formule))
    session.commit()
    return formule


# --------------------------------------------------------------- références

def references(session: Session) -> dict[str, Any]:
    """Tout ce qu'on peut choisir sur une fiche (formulaire du site et ChatGPT)."""
    params = lire_parametres(session)
    return {
        "formules_repas": [formule_repas_dict(f) for f in lister_formules_repas(session, actives=True)],
        "formules_boissons": [formule_boissons_dict(f) for f in lister_formules_boissons(session, actives=True)],
        "privatisations": [produit_dict(p) for p in lister_produits(session, "privatisation", actifs_seulement=True)],
        "espaces": list(ESPACES),
        "types_ligne": [{"cle": "entree", "libelle": "entrée"}, {"cle": "plat", "libelle": "plat"},
                        {"cle": "dessert", "libelle": "dessert"}, {"cle": "supplement", "libelle": "supplément"}],
        "allergenes": [{"cle": k, "libelle": v} for k, v in allergenes_service.tous(session).items()],
        "statuts_fiche": [{"cle": k, "libelle": v} for k, v in LIBELLES_STATUTS_FICHE.items()],
        "heures_proposees": params.get("heures_proposees", []),
        "unites": [{"cle": k, "libelle": v} for k, v in LIBELLES_UNITES.items()],
        "categories": [{"cle": k, "libelle": v} for k, v in LIBELLES_CATEGORIES.items()],
        "couleurs_boissons": list(COULEURS_BOISSONS),
    }


def formule_utilisee(session: Session, formule: Any) -> bool:
    colonne = Fiche.formule_repas_id if isinstance(formule, FormuleRepas) else Fiche.formule_boissons_id
    return bool(session.scalar(select(func.count()).select_from(Fiche).where(colonne == formule.id)))

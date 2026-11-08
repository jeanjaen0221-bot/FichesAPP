"""Migrations : `alembic upgrade head` (lancé au démarrage du conteneur)."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from albert import models  # noqa: F401 - enregistre les tables
from albert.db import Base, creer_moteur
from albert.config import reglages

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

URL = config.attributes.get("url") or reglages.database_url


def run_migrations_offline() -> None:
    context.configure(url=URL, target_metadata=Base.metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


# Tables propres à l'ancienne version : si la base les contient, c'est celle de l'ancien
# site (service Railway réutilisé par erreur). La v2 doit avoir sa propre base ; elle
# refuse d'y installer ses tables, ce qui mélangerait les deux (la table « note »
# existe dans les deux versions).
TABLES_ANCIENNE_VERSION = ("reservation", "reservationitem", "menuitem")


def run_migrations_online() -> None:
    from sqlalchemy import inspect

    moteur = creer_moteur(URL)
    # Connexion à part : inspecter ouvre une transaction ; faite sur la connexion des
    # migrations, elle les englobait et les annulait à la fermeture (rien n'était créé).
    with moteur.connect() as controle:
        anciennes = [t for t in TABLES_ANCIENNE_VERSION if inspect(controle).has_table(t)]
    with moteur.connect() as connexion:
        if anciennes:
            raise SystemExit(
                "ARRÊT : cette base est celle de l'ancienne version (tables "
                + ", ".join(anciennes)
                + "). La v2 ne s'y installe pas. Donner à la v2 une NOUVELLE base PostgreSQL "
                "(variable DATABASE_URL) ; l'ancienne base ne se lit qu'avec le script de reprise."
            )
        context.configure(connection=connexion, target_metadata=Base.metadata, render_as_batch=True,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

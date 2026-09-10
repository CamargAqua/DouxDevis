"""CLI d'administration des tenants Reverso.

Seul moyen d'ajouter/gérer un client — pas de self-service web (la vente reste
une conversation humaine). Nécessite DATABASE_URL et la migration 001 appliquée.

    python manage_tenants.py create-tenant --slug client1 --maison-name "..." \
        --logo-path logo.png --coefficients-json coefficients.json --admin-password "..."
    python manage_tenants.py list-tenants
    python manage_tenants.py set-password --slug client1 --admin-password "..."
    python manage_tenants.py deactivate --slug client1
    python manage_tenants.py activate --slug client1
    python manage_tenants.py set-limit --slug client1 --limit 250
    python manage_tenants.py reset-month --slug client1
"""
from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

if sys.stdout.encoding != "utf-8":  # console Windows par défaut en cp1252, plante sur les accents/flèches
    sys.stdout.reconfigure(encoding="utf-8")

from . import db

load_dotenv()


def _logo_to_png(path: str | None) -> bytes | None:
    """Normalise n'importe quelle image en PNG (disque Render éphémère → stockage DB)."""
    if not path:
        return None
    from PIL import Image
    buf = BytesIO()
    Image.open(path).convert("RGBA").save(buf, format="PNG")
    return buf.getvalue()


def _load_coefficients(path: str | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_create(args):
    if db.get_tenant_by_slug(args.slug):
        sys.exit(f"Tenant '{args.slug}' existe déjà.")
    t = db.create_tenant(
        slug=args.slug,
        maison_name=args.maison_name,
        admin_password_hash=generate_password_hash(args.admin_password),
        coefficients=_load_coefficients(args.coefficients_json),
        logo_png=_logo_to_png(args.logo_path),
        template_key=args.template_key,
        legal_footer=args.legal_footer,
    )
    print(f"Créé : {t.slug} ({t.maison_name}) — {len(t.coefficients)} marque(s), "
          f"logo={'oui' if t.logo_png else 'non'}, legal_footer={t.legal_footer}")


def cmd_list(args):
    tenants = db.list_tenants()
    if not tenants:
        print("Aucun tenant.")
        return
    for t in tenants:
        flag = "actif" if t.active else "SUSPENDU"
        print(f"  {t.slug:<16} {t.maison_name:<28} {len(t.coefficients):>3} marques  "
              f"logo={'o' if t.logo_png else '-'}  legal={'o' if t.legal_footer else '-'}  [{flag}]")


def cmd_set_password(args):
    if not db.get_tenant_by_slug(args.slug):
        sys.exit(f"Tenant '{args.slug}' introuvable.")
    db.set_admin_password_hash(args.slug, generate_password_hash(args.admin_password))
    print(f"Mot de passe admin mis à jour pour '{args.slug}'.")


def cmd_set_active(args, active: bool):
    if not db.get_tenant_by_slug(args.slug):
        sys.exit(f"Tenant '{args.slug}' introuvable.")
    db.set_active(args.slug, active)
    print(f"Tenant '{args.slug}' → {'actif' if active else 'suspendu'}.")


def cmd_set_limit(args):
    if not db.get_tenant_by_slug(args.slug):
        sys.exit(f"Tenant '{args.slug}' introuvable.")
    db.set_devis_limit(args.slug, args.limit)
    print(f"Tenant '{args.slug}' → limite mensuelle de devis = {args.limit}.")


def cmd_reset_month(args):
    if not db.get_tenant_by_slug(args.slug):
        sys.exit(f"Tenant '{args.slug}' introuvable.")
    deleted = db.reset_monthly_devis_count(args.slug)
    print(f"Tenant '{args.slug}' → compteur du mois remis à 0 ({deleted} entrée(s) supprimée(s)).")


def main():
    p = argparse.ArgumentParser(description="Gestion des tenants Reverso")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create-tenant")
    c.add_argument("--slug", required=True)
    c.add_argument("--maison-name", required=True)
    c.add_argument("--admin-password", required=True)
    c.add_argument("--coefficients-json", default=None)
    c.add_argument("--logo-path", default=None)
    c.add_argument("--template-key", default="doux")
    c.add_argument("--legal-footer", action="store_true")
    c.set_defaults(func=cmd_create)

    c = sub.add_parser("list-tenants")
    c.set_defaults(func=cmd_list)

    c = sub.add_parser("set-password")
    c.add_argument("--slug", required=True)
    c.add_argument("--admin-password", required=True)
    c.set_defaults(func=cmd_set_password)

    c = sub.add_parser("deactivate")
    c.add_argument("--slug", required=True)
    c.set_defaults(func=lambda a: cmd_set_active(a, False))

    c = sub.add_parser("activate")
    c.add_argument("--slug", required=True)
    c.set_defaults(func=lambda a: cmd_set_active(a, True))

    c = sub.add_parser("set-limit")
    c.add_argument("--slug", required=True)
    c.add_argument("--limit", required=True, type=int)
    c.set_defaults(func=cmd_set_limit)

    c = sub.add_parser("reset-month")
    c.add_argument("--slug", required=True)
    c.set_defaults(func=cmd_reset_month)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

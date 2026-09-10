"""Accès Postgres — couche plate, pas d'ORM (une seule table `tenants`).

Dans une requête Flask, la connexion vit dans `g` (ouverte à la demande, fermée
en teardown). Hors Flask (CLI, auto-test), on ouvre/ferme une connexion directe.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg2
from psycopg2.extras import Json


@dataclass
class Tenant:
    slug: str
    maison_name: str
    logo_png: bytes | None
    coefficients: dict
    admin_password_hash: str
    template_key: str
    legal_footer: bool
    active: bool
    devis_limit: int | None
    feature_creation: bool
    feature_sav_rapide: bool
    feature_bijoux3_export: bool


_COLS = (
    "slug, maison_name, logo_png, coefficients, admin_password_hash, "
    "template_key, legal_footer, active, devis_limit, feature_creation, feature_sav_rapide, "
    "feature_bijoux3_export"
)


def _row_to_tenant(row) -> Tenant:
    (slug, maison_name, logo_png, coefficients, pwd_hash, template_key, legal_footer, active,
     devis_limit, feature_creation, feature_sav_rapide, feature_bijoux3_export) = row
    return Tenant(
        slug=slug,
        maison_name=maison_name,
        logo_png=bytes(logo_png) if logo_png is not None else None,
        coefficients=coefficients or {},
        admin_password_hash=pwd_hash,
        template_key=template_key,
        legal_footer=legal_footer,
        active=active,
        devis_limit=devis_limit,
        feature_creation=feature_creation,
        feature_sav_rapide=feature_sav_rapide,
        feature_bijoux3_export=feature_bijoux3_export,
    )


def _connect():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL non définie.")
    return psycopg2.connect(dsn)


def get_conn():
    """Connexion partagée dans le contexte de requête Flask ; sinon connexion directe.

    ponytail: une connexion par requête, ajouter psycopg2.pool si la latence devient visible.
    """
    try:
        from flask import g  # import local : db.py utilisable hors Flask (CLI)
        if "db_conn" not in g:
            g.db_conn = _connect()
        return g.db_conn
    except RuntimeError:
        # Hors contexte d'application Flask (CLI, __main__)
        return _connect()


def close_conn(exc=None):
    from flask import g
    conn = g.pop("db_conn", None)
    if conn is not None:
        conn.close()


def get_tenant_by_slug(slug: str) -> Tenant | None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLS} FROM tenants WHERE slug = %s", (slug,))
        row = cur.fetchone()
    return _row_to_tenant(row) if row else None


def list_tenants() -> list[Tenant]:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLS} FROM tenants ORDER BY slug")
        rows = cur.fetchall()
    return [_row_to_tenant(r) for r in rows]


def create_tenant(slug: str, maison_name: str, admin_password_hash: str,
                  coefficients: dict | None = None, logo_png: bytes | None = None,
                  template_key: str = "doux", legal_footer: bool = False,
                  devis_limit: int | None = None, feature_creation: bool = False,
                  feature_sav_rapide: bool = False, feature_bijoux3_export: bool = False) -> Tenant:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants "
            "(slug, maison_name, logo_png, coefficients, admin_password_hash, template_key, "
            "legal_footer, devis_limit, feature_creation, feature_sav_rapide, feature_bijoux3_export) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (slug, maison_name, psycopg2.Binary(logo_png) if logo_png else None,
             Json(coefficients or {}), admin_password_hash, template_key, legal_footer, devis_limit,
             feature_creation, feature_sav_rapide, feature_bijoux3_export),
        )
    conn.commit()
    return get_tenant_by_slug(slug)


def save_tenant_coefficients(slug: str, data: dict) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("UPDATE tenants SET coefficients = %s WHERE slug = %s", (Json(data), slug))
    conn.commit()


def set_admin_password_hash(slug: str, password_hash: str) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("UPDATE tenants SET admin_password_hash = %s WHERE slug = %s", (password_hash, slug))
    conn.commit()


def set_active(slug: str, active: bool) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("UPDATE tenants SET active = %s WHERE slug = %s", (active, slug))
    conn.commit()


def set_devis_limit(slug: str, devis_limit: int | None) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("UPDATE tenants SET devis_limit = %s WHERE slug = %s", (devis_limit, slug))
    conn.commit()


def update_tenant_profile(slug: str, maison_name: str, legal_footer: bool, active: bool,
                          devis_limit: int | None, feature_creation: bool = False,
                          feature_sav_rapide: bool = False, feature_bijoux3_export: bool = False) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tenants SET maison_name = %s, legal_footer = %s, active = %s, devis_limit = %s, "
            "feature_creation = %s, feature_sav_rapide = %s, feature_bijoux3_export = %s WHERE slug = %s",
            (maison_name, legal_footer, active, devis_limit, feature_creation, feature_sav_rapide,
             feature_bijoux3_export, slug),
        )
    conn.commit()


def delete_tenant(slug: str) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM tenants WHERE slug = %s", (slug,))
    conn.commit()


def log_devis(slug: str) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO devis_log (tenant_slug) VALUES (%s)", (slug,))
    conn.commit()


def get_monthly_devis_count(slug: str) -> int:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM devis_log "
            "WHERE tenant_slug = %s AND created_at >= date_trunc('month', now())",
            (slug,),
        )
        return cur.fetchone()[0]


def reset_monthly_devis_count(slug: str) -> int:
    """Supprime les entrées devis_log du mois en cours pour ce tenant (débloque le quota
    mensuel sans toucher au total historique). Renvoie le nombre de lignes supprimées."""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM devis_log WHERE tenant_slug = %s AND created_at >= date_trunc('month', now())",
            (slug,),
        )
        deleted = cur.rowcount
    conn.commit()
    return deleted


def get_devis_counts() -> dict[str, dict[str, int]]:
    """Compte mensuel + total par tenant, en une seule requête (évite le N+1 sur la liste admin)."""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tenant_slug, "
            "count(*) FILTER (WHERE created_at >= date_trunc('month', now())), "
            "count(*) "
            "FROM devis_log GROUP BY tenant_slug"
        )
        rows = cur.fetchall()
    return {slug: {"month": month, "total": total} for slug, month, total in rows}


def update_tenant_logo(slug: str, logo_png: bytes | None) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tenants SET logo_png = %s WHERE slug = %s",
            (psycopg2.Binary(logo_png) if logo_png else None, slug),
        )
    conn.commit()


def create_creation(slug: str, client_nom: str, description: str, prix_ht: float) -> int:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO creations (tenant_slug, client_nom, description, prix_ht) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (slug, client_nom, description, prix_ht),
        )
        new_id = cur.fetchone()[0]
    conn.commit()
    return new_id


def list_creations(slug: str, limit: int = 50) -> list[dict]:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, client_nom, description, prix_ht, created_at FROM creations "
            "WHERE tenant_slug = %s ORDER BY created_at DESC LIMIT %s",
            (slug, limit),
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "client_nom": r[1], "description": r[2], "prix_ht": r[3], "created_at": r[4]}
        for r in rows
    ]


if __name__ == "__main__":
    # Auto-test : insert → read → update → delete sur un slug jetable.
    # Nécessite DATABASE_URL + migration 001 déjà appliquée.
    _SLUG = "__selftest__"
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE slug = %s", (_SLUG,))
        conn.commit()
    finally:
        conn.close()

    from werkzeug.security import generate_password_hash, check_password_hash

    t = create_tenant(_SLUG, "Selftest", generate_password_hash("pw"),
                       coefficients={"Rolex": {"coeff": 1.2, "base": "ht"}})
    assert t is not None and t.slug == _SLUG
    assert t.coefficients["Rolex"]["coeff"] == 1.2
    assert check_password_hash(t.admin_password_hash, "pw")
    assert t.active is True and t.legal_footer is False

    save_tenant_coefficients(_SLUG, {"Omega": {"coeff": 1.6, "base": "ht"}})
    t2 = get_tenant_by_slug(_SLUG)
    assert "Omega" in t2.coefficients and "Rolex" not in t2.coefficients

    set_active(_SLUG, False)
    assert get_tenant_by_slug(_SLUG).active is False

    assert any(x.slug == _SLUG for x in list_tenants())

    update_tenant_profile(_SLUG, "Selftest", legal_footer=False, active=True, devis_limit=1)
    assert get_tenant_by_slug(_SLUG).devis_limit == 1

    assert get_monthly_devis_count(_SLUG) == 0
    log_devis(_SLUG)
    log_devis(_SLUG)
    assert get_monthly_devis_count(_SLUG) == 2
    counts = get_devis_counts()
    assert counts[_SLUG] == {"month": 2, "total": 2}

    delete_tenant(_SLUG)
    assert get_tenant_by_slug(_SLUG) is None
    assert _SLUG not in get_devis_counts()  # cascade a bien supprimé devis_log

    print("db.py self-test OK")

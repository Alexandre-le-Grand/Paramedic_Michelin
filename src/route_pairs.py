"""Utilitaires pour les paires depart / arrivee (deduplication aller-retour)."""
from __future__ import annotations


def pair_key(depart: str, arrivee: str) -> tuple[str, str]:
    """Cle canonique : meme trajet que l'inverse (Paris-Bordeaux = Bordeaux-Paris)."""
    a, b = depart.strip(), arrivee.strip()
    return (a, b) if a <= b else (b, a)


def dedupe_bidirectional(
    routes: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], int]:
    """
    Garde une seule direction par paire de villes.
    Retourne (liste, nombre de trajets ignores).
    """
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    skipped = 0
    for depart, arrivee in routes:
        depart = depart.strip()
        arrivee = arrivee.strip()
        if not depart or not arrivee or depart == arrivee:
            continue
        key = pair_key(depart, arrivee)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        out.append((depart, arrivee))
    return out, skipped

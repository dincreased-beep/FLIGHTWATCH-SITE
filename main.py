#!/usr/bin/env python3
"""FlightWatch — point d'entrée.

Usage :
    python main.py run                 # cycle complet (cron)
    python main.py run --dry-run       # collecte + analyse, sans e-mail
    python main.py backfill            # collecte seule, pour bâtir l'historique
    python main.py stats               # état de la base
    python main.py test-email          # vérifie la config SMTP
"""

from __future__ import annotations

import argparse
import logging
import sys

from config import load_config
import climate as climate_mod
import periods as periods_mod
import tips as tips_mod
import website
import places
from notify import render_text, send_email
from scoring import Deal, apply_filters, find_deals
from sources import Offer, TravelpayoutsClient, collect
from store import Store
from verify import verify_deals


def build_client(cfg) -> TravelpayoutsClient:
    try:
        return TravelpayoutsClient(cfg.secrets.travelpayouts_token, cfg.http)
    except ValueError as exc:
        raise SystemExit(
            f"{exc}\nCrée un token gratuit sur "
            "https://www.travelpayouts.com/developers/api puis exporte-le :\n"
            "  export TRAVELPAYOUTS_TOKEN=xxxxxxxx"
        ) from None


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_run(args, cfg) -> int:
    store = Store(cfg.db_path)
    try:
        client = build_client(cfg)
        windows = periods_mod.load_periods(cfg)
        offers = collect(client, cfg, periods_mod.months_to_scan(windows))
        logging.info("%s offres brutes collectées", len(offers))

        offers = apply_filters(offers, cfg, windows)
        logging.info("%s offres après filtres", len(offers))

        deals = find_deals(offers, store, cfg)
        store.record(offers)          # après le scoring, pour ne pas polluer
        logging.info("%s bonne(s) affaire(s) détectée(s)", len(deals))

        cap = int(cfg.alerting.get("max_deals_per_email", 20))
        deals = deals[:cap]

        if not deals:
            logging.info("Rien à signaler.")
            return 0

        if not args.no_verify:
            deals = verify_deals(deals, cfg, store)
            if not deals:
                logging.info("Toutes les offres ont été écartées après "
                             "vérification.")
                return 0

        climate_mod.enrich(deals, store, cfg)

        jours = int(cfg.raw.get("display", {}).get("history_days", 31))
        for d in deals:
            d.series = store.price_series(d.offer.origin, d.offer.destination,
                                          d.offer.trip_class, jours)
        tips_mod.enrich(deals, store, cfg)

        if args.dry_run:
            print(render_text(deals))
            return 0

        if send_email(deals, cfg):
            for d in deals:
                store.log_alert(d.offer)
        return 0
    finally:
        store.close()


def cmd_backfill(args, cfg) -> int:
    """Collecte sans alerter — à lancer les premiers jours pour constituer
    un historique avant que la détection d'anomalie ait du sens."""
    store = Store(cfg.db_path)
    try:
        client = build_client(cfg)
        windows = periods_mod.load_periods(cfg)
        offers = apply_filters(
            collect(client, cfg, periods_mod.months_to_scan(windows)),
            cfg, windows)
        added = store.record(offers)
        logging.info("%s observations ajoutées (%s vues)", added, len(offers))
        return 0
    finally:
        store.close()


def cmd_site(args, cfg) -> int:
    """Génère le site statique à partir de la base."""
    store = Store(cfg.db_path)
    try:
        n = website.build(store, cfg, args.out)
        print(f"{n} pages écrites dans {args.out}")
        return 0
    finally:
        store.close()


def cmd_stats(args, cfg) -> int:
    store = Store(cfg.db_path)
    try:
        s = store.stats()
        print(f"Observations     : {s['observations']}")
        print(f"Destinations     : {s['destinations']}")
        print(f"  dont affaires  : {s['business']} observations")
        print(f"Jours d'historique: {s['days_of_history']}")
        print(f"Alertes envoyées : {s['alerts']}")
        quota = cfg.raw.get("verification", {}).get("monthly_quota", 250)
        print(f"SerpApi ce mois  : {s['serpapi_this_month']} / {quota}")
        min_hist = cfg.alerting.get("min_history", 4)
        if s["days_of_history"] < min_hist:
            print(f"\n⚠ Historique encore court : la détection par médiane "
                  f"ne s'activera qu'à partir de {min_hist} relevés par route.")
        return 0
    finally:
        store.close()


def cmd_test_email(args, cfg) -> int:
    demo = Offer(origin="MRS", destination="BKK", depart_date="2026-11-12",
                 return_date="2026-11-28", price=412.0, currency="eur",
                 transfers=1, source="demo", found_at="")
    deal = Deal(offer=demo, reasons=["test de configuration"], median=690.0,
                discount_pct=40.3, history_size=12, is_all_time_low=True)
    ok = send_email([deal], cfg)
    print("Envoyé." if ok else "Échec — voir les logs ci-dessus.")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(prog="flightwatch")
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="cycle complet")
    r.add_argument("--dry-run", action="store_true",
                   help="afficher au lieu d'envoyer")
    r.add_argument("--no-verify", action="store_true",
                   help="sauter l'étage SerpApi (économise le quota)")
    r.set_defaults(func=cmd_run)

    sub.add_parser("backfill", help="collecte sans alerte").set_defaults(
        func=cmd_backfill)
    w = sub.add_parser("site", help="générer le site statique")
    w.add_argument("--out", default="site", help="dossier de sortie")
    w.set_defaults(func=cmd_site)

    sub.add_parser("stats", help="état de la base").set_defaults(func=cmd_stats)
    sub.add_parser("test-email", help="tester la config SMTP").set_defaults(
        func=cmd_test_email)

    args = p.parse_args()
    setup_logging(args.verbose)
    cfg = load_config(args.config)
    display = cfg.raw.get("display", {})
    places.init(cfg.db_path.parent,
                lang=display.get("names_language", "fr"),
                enabled=display.get("full_destination_names", True))
    return args.func(args, cfg)


if __name__ == "__main__":
    sys.exit(main())

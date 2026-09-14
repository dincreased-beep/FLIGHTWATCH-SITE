"""Génération du site statique à partir de la base.

L'e-mail pousse ce qui sort de l'ordinaire. Le site, lui, montre tout : les
centaines d'observations quotidiennes qui ne déclenchent rien et qu'on ne voit
jamais aujourd'hui. C'est là qu'on peut se demander « où en est Bangkok ? »
sans attendre qu'une alerte tombe.

Trois pages :
    index.html            toutes les routes suivies, état courant
    r/<code>.html         une route : courbe complète, relevés, jour de réservation
    alertes.html          historique des alertes envoyées

Aucune dépendance externe, aucun script tiers : le site fonctionne hors ligne
et ne traque personne. Il sera chiffré par StatiCrypt avant publication.
"""

from __future__ import annotations

import datetime as dt
import html
import logging
import statistics
from pathlib import Path

import places
from notify import (BIZ, BORDER, CRIMSON, ECO, EMERALD, GOLD, INK, MONO, MUTED,
                    PAPER, SANS, SERIF, _date_fr, _money)
from tips import JOURS_COURTS, booking_day

log = logging.getLogger(__name__)

CSS = f"""
*{{box-sizing:border-box}}
body{{margin:0;background:{PAPER};color:{INK};font-family:{SANS};
     -webkit-font-smoothing:antialiased;line-height:1.5}}
.wrap{{max-width:1080px;margin:0 auto;padding:0 16px 56px}}
header.top{{background:{INK};color:#fff;padding:24px 0 22px;margin-bottom:24px}}
header.top .wrap{{padding-bottom:0}}
.kicker{{font-size:10px;font-weight:700;letter-spacing:2.4px;color:#8f9bb8}}
h1{{font-family:{SERIF};font-size:30px;margin:6px 0 0;font-weight:700}}
h2{{font-family:{SERIF};font-size:21px;margin:30px 0 12px;font-weight:700}}
.sub{{font-size:12.5px;color:#9aa3bd;margin-top:8px}}
nav a{{color:#cfd6e8;text-decoration:none;font-size:12.5px;margin-right:18px;
      border-bottom:1px solid transparent;padding-bottom:2px}}
nav a:hover,nav a.on{{border-bottom-color:#cfd6e8}}
.card{{background:#fff;border:1px solid {BORDER};border-radius:10px;
      overflow:hidden;box-shadow:0 1px 3px rgba(20,22,31,.06)}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th{{text-align:left;font-size:9.5px;font-weight:700;letter-spacing:.9px;
   text-transform:uppercase;color:{MUTED};padding:10px 12px;
   background:#fbfbfd;border-bottom:1px solid {BORDER};white-space:nowrap}}
td{{padding:11px 12px;border-bottom:1px solid #f2f2f7;vertical-align:middle;
   font-variant-numeric:tabular-nums}}
tr:last-child td{{border-bottom:0}}
tbody tr:hover{{background:#fafbff}}
.dest{{font-family:{SERIF};font-size:15px;font-weight:700}}
.dest a{{color:{INK};text-decoration:none}}
.dest a:hover{{text-decoration:underline}}
.price{{font-family:{SERIF};font-size:17px;font-weight:700;text-align:right;
       white-space:nowrap}}
.tag{{display:inline-block;border-radius:10px;padding:2px 8px;font-size:9px;
     font-weight:700;letter-spacing:.7px;text-transform:uppercase;color:#fff;
     margin-left:6px;vertical-align:middle}}
.spark{{display:flex;align-items:flex-end;gap:1px;height:30px}}
.spark i{{flex:1;border-radius:1px;min-width:2px}}
.mut{{color:{MUTED};font-size:11.5px}}
.up{{color:{CRIMSON}}} .down{{color:{EMERALD}}}
.day{{display:inline-block;width:13%;text-align:center;border-radius:6px;
     padding:6px 2px;margin-right:.6%;font-size:12px}}
.day b{{display:block;font-size:10px;color:{MUTED};letter-spacing:.5px}}
.note{{background:#fff;border:1px solid {BORDER};border-radius:10px;
      padding:16px 18px;margin-top:22px;font-size:12px;color:{MUTED};
      line-height:1.75}}
.back{{font-size:12.5px;color:{ECO};text-decoration:none}}
.search{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;
        margin-bottom:16px}}
#q{{flex:1;min-width:220px;font-family:{SANS};font-size:15px;padding:12px 14px;
   border:1px solid {BORDER};border-radius:9px;background:#fff;color:{INK};
   outline:none}}
#q:focus{{border-color:{ECO};box-shadow:0 0 0 3px rgba(15,90,110,.10)}}
.chip{{font-size:12px;font-weight:600;padding:9px 14px;border-radius:9px;
      border:1px solid {BORDER};background:#fff;color:{MUTED};cursor:pointer;
      font-family:{SANS}}}
.chip.on{{background:{INK};color:#fff;border-color:{INK}}}
#count{{font-size:12px;color:{MUTED};margin-bottom:10px}}
#empty{{display:none;padding:26px;text-align:center;color:{MUTED}}}
th[data-sort]:hover{{color:{INK}}}
@media(max-width:640px){{
  h1{{font-size:24px}} .hide-sm{{display:none}} td,th{{padding:9px 8px}}
}}
"""


# Le script est servi dans un fichier séparé, volontairement. StatiCrypt
# reconstruit la page après déchiffrement, et selon la version, un <script>
# écrit dans le corps peut ne pas s'exécuter ; un <script src> est toujours
# chargé. Le fichier ne contient que de la logique d'affichage, aucun prix :
# le laisser en clair dans le dépôt public ne révèle rien.
JS = """
(function () {
  function init() {
    var q = document.getElementById('q');
    var rows = Array.prototype.slice.call(
      document.querySelectorAll('tbody tr[data-search]'));
    if (!rows.length) return;
    var count = document.getElementById('count');
    var empty = document.getElementById('empty');
    var chips = Array.prototype.slice.call(document.querySelectorAll('.chip'));
    var classe = 'all';

    function norm(s) {
      return (s || '').toLowerCase()
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    }

    function apply() {
      var terme = norm(q ? q.value : '');
      var n = 0;
      rows.forEach(function (tr) {
        var okTexte = !terme || norm(tr.getAttribute('data-search')).indexOf(terme) > -1;
        var okClasse = classe === 'all' || tr.getAttribute('data-class') === classe;
        var visible = okTexte && okClasse;
        tr.style.display = visible ? '' : 'none';
        if (visible) n++;
      });
      if (count) count.textContent = n + (n > 1 ? ' destinations' : ' destination');
      if (empty) empty.style.display = n ? 'none' : 'block';
    }

    if (q) {
      q.addEventListener('input', apply);
      q.addEventListener('search', apply);
    }
    chips.forEach(function (c) {
      c.addEventListener('click', function () {
        chips.forEach(function (x) { x.classList.remove('on'); });
        c.classList.add('on');
        classe = c.getAttribute('data-filter');
        apply();
      });
    });

    // Tri au clic sur un en-tête portant data-sort.
    var sens = {};
    document.querySelectorAll('th[data-sort]').forEach(function (th) {
      th.style.cursor = 'pointer';
      th.addEventListener('click', function () {
        var cle = th.getAttribute('data-sort');
        sens[cle] = !sens[cle];
        var corps = rows[0].parentNode;
        rows.sort(function (a, b) {
          var x = parseFloat(a.getAttribute('data-' + cle)) || 0;
          var y = parseFloat(b.getAttribute('data-' + cle)) || 0;
          return sens[cle] ? x - y : y - x;
        }).forEach(function (tr) { corps.appendChild(tr); });
      });
    });

    apply();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else { init(); }
})();
"""


def _esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


def _page(titre: str, corps: str, actif: str = "", prefixe: str = "") -> str:
    on = lambda k: ' class="on"' if k == actif else ""  # noqa: E731
    return f"""<!doctype html><html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport"
  content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{_esc(titre)} — FlightWatch</title><style>{CSS}</style>
<script src="{prefixe}app.js" defer></script></head><body>
<header class="top"><div class="wrap">
  <div class="kicker">FLIGHTWATCH</div>
  <h1>{_esc(titre)}</h1>
  <div class="sub">Mis à jour le {dt.datetime.now():%d/%m/%Y à %H:%M}</div>
  <nav style="margin-top:14px">
    <a href="{prefixe}index.html"{on('index')}>Destinations</a>
    <a href="{prefixe}alertes.html"{on('alertes')}>Alertes envoyées</a>
  </nav>
</div></header>
<div class="wrap">{corps}
<div class="note">
  Prix relevés par la veille Aviasales, indicatifs : à vérifier avant
  réservation. Climat et fuseaux horaires d'après Open-Meteo.com
  (ERA5, CC&nbsp;BY&nbsp;4.0). Page privée, non indexée.
</div></div></body></html>"""


def _spark(prix: list[float], accent: str) -> str:
    if len(prix) < 3:
        return ""
    bas, haut = min(prix), max(prix)
    etendue = (haut - bas) or 1
    barres = "".join(
        f'<i style="height:{max(8, round((p - bas) / etendue * 92) + 8)}%;'
        f'background:{accent if p <= bas * 1.03 else "#d2d2dd"}"></i>'
        for p in prix)
    return f'<div class="spark">{barres}</div>'


def _trend(prix: list[float]) -> tuple[str, str]:
    if len(prix) < 8:
        return "", ""
    moitie = max(1, len(prix) // 2)
    debut = sum(prix[:moitie]) / moitie
    var = (prix[-1] - debut) / debut * 100 if debut else 0
    if var <= -4:
        return "down", f"&#9660; {var:.0f} %"
    if var >= 8:
        return "up", f"&#9650; +{var:.0f} %"
    return "mut", "&#9644; stable"


def _slug(route: dict) -> str:
    return f"{route['origin']}-{route['destination']}-{route['trip_class']}"


# --------------------------------------------------------------------------
def _index(store, routes: list[dict]) -> str:
    lignes = []
    for r in routes:
        serie = store.price_series(r["origin"], r["destination"],
                                   r["trip_class"], 60)
        prix = [p for _, p in serie]
        if not prix:
            continue
        accent = BIZ if r["trip_class"] == 1 else ECO
        cls, txt = _trend(prix)
        cabine = (f'<span class="tag" style="background:{BIZ}">affaires</span>'
                  if r["trip_class"] == 1 else "")
        cur = r["currency"] or "eur"
        record = ('<span class="tag" style="background:%s">au plus bas</span>'
                  % EMERALD if prix[-1] <= min(prix) * 1.01 else "")
        # Tout ce sur quoi la recherche doit mordre : nom de ville, pays,
        # codes IATA, et le nom de l'origine.
        cible = " ".join([
            places.label(r["destination"]),
            places.short(r["destination"]),
            places.label(r["origin"], False),
            r["destination"], r["origin"],
            "affaires" if r["trip_class"] == 1 else "economique",
        ])
        var = 0.0
        if len(prix) >= 8:
            moitie = max(1, len(prix) // 2)
            deb = sum(prix[:moitie]) / moitie
            var = (prix[-1] - deb) / deb * 100 if deb else 0

        lignes.append(f"""
        <tr data-search="{_esc(cible)}"
            data-class="{'biz' if r['trip_class'] == 1 else 'eco'}"
            data-price="{prix[-1]:.0f}" data-var="{var:.1f}"
            data-days="{r['jours']}">
          <td class="dest"><a href="r/{_slug(r)}.html">
            {_esc(places.label(r['destination']))}</a>{cabine}{record}
            <div class="mut">depuis {_esc(places.label(r['origin'], False))}
              &middot; {_esc(r['origin'])}&ndash;{_esc(r['destination'])}</div></td>
          <td class="hide-sm" width="150">{_spark(prix, accent)}</td>
          <td class="{cls}" width="90">{txt}</td>
          <td class="hide-sm mut" width="110">{r['jours']} j
            <div class="mut">plus bas {_money(min(prix), cur)}</div></td>
          <td class="price" style="color:{accent}">{_money(prix[-1], cur)}</td>
        </tr>""")

    if not lignes:
        return ('<div class="card" style="padding:26px"><b>Aucun relevé pour '
                "l'instant.</b><div class=\"mut\" style=\"padding-top:6px\">"
                "La base se remplit à chaque cycle ; reviens dans un jour ou "
                "deux.</div></div>")

    return f"""
    <div class="search">
      <input id="q" type="search" autocomplete="off"
             placeholder="Rechercher une destination, un pays, un code…">
      <button class="chip on" data-filter="all">Toutes</button>
      <button class="chip" data-filter="eco">Économique</button>
      <button class="chip" data-filter="biz">Affaires</button>
    </div>
    <div id="count">{len(lignes)} destinations</div>
    <div class="card"><table>
      <thead><tr><th>Destination</th><th class="hide-sm">30 derniers jours</th>
        <th data-sort="var">Tendance &#8645;</th>
        <th class="hide-sm" data-sort="days">Relevés &#8645;</th>
        <th data-sort="price" style="text-align:right">Prix du jour &#8645;</th>
      </tr></thead>
      <tbody>{''.join(lignes)}</tbody>
    </table>
    <div id="empty">Aucune destination ne correspond.<br>
      <span class="mut">La liste ne contient que les routes déjà observées ;
        elle s'étoffe à chaque cycle.</span></div>
    </div>"""


def _route_page(store, r: dict) -> str:
    serie = store.price_series(r["origin"], r["destination"],
                               r["trip_class"], 400)
    prix = [p for _, p in serie]
    cur = r["currency"] or "eur"
    accent = BIZ if r["trip_class"] == 1 else ECO
    cls, txt = _trend(prix)

    # Jour de réservation
    bloc_jour = ""
    t = booking_day(serie)
    if t:
        cases = []
        for j in range(7):
            idx = t.indices.get(j)
            if idx is None:
                fond, coul, val = "#f4f4f8", "#b4b4c2", "·"
            else:
                ecart = (idx - 1) * 100
                val = f"{ecart:+.0f}%"
                fond, coul = (("#e6f5ef", EMERALD) if ecart <= -3 else
                              ("#fdeeed", CRIMSON) if ecart >= 3 else
                              ("#f4f4f8", "#6a6a7a"))
            bord = f"2px solid {EMERALD}" if t.best_day == j else "2px solid transparent"
            cases.append(f'<span class="day" style="background:{fond};'
                         f'border:{bord};color:{coul}">'
                         f'<b>{JOURS_COURTS[j]}</b>{val}</span>')
        bloc_jour = f"""
        <h2>Quand réserver</h2>
        <div class="card" style="padding:16px 18px">
          <div>{''.join(cases)}</div>
          <div style="padding-top:12px;font-size:13px">{_esc(t.text)}</div>
        </div>"""

    # Relevés récents
    recents = list(reversed(serie))[:45]
    lignes = "".join(
        f"<tr><td>{_date_fr(j)}<span class='mut'> &middot; {j}</span></td>"
        f"<td class='price' style='color:{accent}'>{_money(p, cur)}</td></tr>"
        for j, p in recents)

    med = statistics.median(prix) if prix else 0
    return _page(
        places.label(r["destination"]),
        f"""
    <a class="back" href="../index.html">&larr; Toutes les destinations</a>
    <h2>{_esc(places.label(r['origin'], False))} &rarr;
      {_esc(places.label(r['destination']))}
      {'<span class="tag" style="background:%s">affaires</span>' % BIZ
       if r['trip_class'] == 1 else ''}</h2>
    <div class="card" style="padding:18px">
      <div style="font-size:30px;font-family:{SERIF};font-weight:700;
          color:{accent}">{_money(prix[-1], cur) if prix else '—'}</div>
      <div class="mut">prix du jour &middot; <span class="{cls}">{txt}</span></div>
      <div style="padding-top:16px">{_spark(prix[-90:], accent)}</div>
      <div class="mut" style="padding-top:8px">
        plus bas {_money(min(prix), cur)} &middot;
        médiane {_money(med, cur)} &middot;
        plus haut {_money(max(prix), cur)} &middot;
        {r['jours']} jours de relevés
      </div>
    </div>
    {bloc_jour}
    <h2>Relevés récents</h2>
    <div class="card"><table><thead><tr><th>Jour</th>
      <th style="text-align:right">Meilleur prix</th></tr></thead>
      <tbody>{lignes}</tbody></table></div>""", prefixe="../")


def _alerts_page(store) -> str:
    rows = store.alerts_log(200)
    if not rows:
        corps = ('<div class="card" style="padding:26px">Aucune alerte '
                 "envoyée pour l'instant.</div>")
    else:
        lignes = []
        for a in rows:
            accent = BIZ if a["trip_class"] == 1 else ECO
            cabine = (f'<span class="tag" style="background:{BIZ}">affaires</span>'
                      if a["trip_class"] == 1 else "")
            lignes.append(
                f"<tr><td class='mut'>{_esc(a['sent_at'][:16].replace('T', ' '))}</td>"
                f"<td class='dest'>{_esc(places.label(a['destination']))}{cabine}</td>"
                f"<td class='hide-sm'>{_date_fr(a['depart_date'])}"
                + (f" <span class='mut'>&rarr; {_date_fr(a['return_date'])}</span>"
                   if a["return_date"] else "")
                + f"</td><td class='price' style='color:{accent}'>"
                  f"{_money(a['price'], 'eur')}</td></tr>")
        corps = (f'<div class="card"><table><thead><tr><th>Envoyée</th>'
                 f'<th>Destination</th><th class="hide-sm">Dates</th>'
                 f'<th style="text-align:right">Prix</th></tr></thead>'
                 f'<tbody>{"".join(lignes)}</tbody></table></div>')
    return _page("Alertes envoyées", corps, "alertes")


# --------------------------------------------------------------------------
def build(store, cfg, outdir: str | Path) -> int:
    """Écrit le site. Retourne le nombre de pages produites."""
    out = Path(outdir)
    (out / "r").mkdir(parents=True, exist_ok=True)

    routes = store.routes()
    log.info("Site : %s route(s) suivie(s)", len(routes))

    (out / "index.html").write_text(
        _page("Destinations suivies", _index(store, routes), "index"),
        encoding="utf-8")
    (out / "alertes.html").write_text(_alerts_page(store), encoding="utf-8")
    (out / "app.js").write_text(JS, encoding="utf-8")

    n = 2
    for r in routes:
        try:
            (out / "r" / f"{_slug(r)}.html").write_text(
                _route_page(store, r), encoding="utf-8")
            n += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("Page %s ignorée : %s", _slug(r), exc)
    log.info("Site : %s pages écrites dans %s", n, out)
    return n

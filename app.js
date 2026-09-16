
(function () {
  function init() {
    var q = document.getElementById('q');
    var rows = Array.prototype.slice.call(
      document.querySelectorAll('tbody tr[data-search]'));
    if (!rows.length) return;
    var count = document.getElementById('count');
    var empty = document.getElementById('empty');
    var chips = Array.prototype.slice.call(
      document.querySelectorAll('.chip[data-filter]'));
    var classe = 'all';
    var d1 = document.getElementById('d1');
    var d2 = document.getElementById('d2');
    var duree = document.getElementById('duree');
    var retour = document.getElementById('retour');

    function norm(s) {
      return (s || '').toLowerCase()
        .normalize('NFD').replace(/[̀-ͯ]/g, '');
    }

    function bornesDuree() {
      var v = duree ? duree.value : '';
      if (!v) return null;
      var p = v.split('-');
      return {min: parseInt(p[0], 10), max: parseInt(p[1], 10)};
    }

    function apply() {
      var terme = norm(q ? q.value : '');
      var du = d1 && d1.value ? d1.value : '';
      var au = d2 && d2.value ? d2.value : '';
      var bd = bornesDuree();
      var n = 0;

      rows.forEach(function (tr) {
        var okTexte = !terme ||
          norm(tr.getAttribute('data-search')).indexOf(terme) > -1;
        var okClasse = classe === 'all' ||
          tr.getAttribute('data-class') === classe;

        // Les dates sont en ISO : la comparaison de chaînes suffit et évite
        // les pièges de fuseau d'un Date().
        var dep = tr.getAttribute('data-depart') || '';
        var okDates = true;
        if (du || au) {
          okDates = dep !== '' && (!du || dep >= du) && (!au || dep <= au);
        }

        var okDuree = true;
        if (bd) {
          var nuits = parseInt(tr.getAttribute('data-nuits') || '0', 10);
          okDuree = nuits >= bd.min && nuits <= bd.max;
        }

        var visible = okTexte && okClasse && okDates && okDuree;
        tr.style.display = visible ? '' : 'none';
        if (visible) n++;
      });

      if (count) {
        count.textContent = n + (n > 1 ? ' destinations' : ' destination');
      }
      if (empty) empty.style.display = n ? 'none' : 'block';

      // La flèche n'apparaît que s'il y a quelque chose à annuler.
      var actif = !!(terme || du || au || (bd) || classe !== 'all');
      if (retour) retour.style.display = actif ? 'inline-block' : 'none';
    }

    if (q) {
      q.addEventListener('input', apply);
      q.addEventListener('search', apply);
    }
    [d1, d2, duree].forEach(function (el) {
      if (el) el.addEventListener('change', apply);
    });

    function toutEffacer() {
      if (q) q.value = '';
      if (d1) d1.value = '';
      if (d2) d2.value = '';
      if (duree) duree.value = '';
      classe = 'all';
      chips.forEach(function (c) {
        c.classList.toggle('on', c.getAttribute('data-filter') === 'all');
      });
      document.querySelectorAll('.pays.selection').forEach(function (el) {
        el.classList.remove('selection');
      });
      var r = document.getElementById('reset');
      if (r) r.style.display = 'none';
      apply();
      window.scrollTo({top: 0, behavior: 'smooth'});
    }

    var vider = document.getElementById('vider');
    if (vider) vider.addEventListener('click', toutEffacer);
    if (retour) retour.addEventListener('click', function (e) {
      e.preventDefault(); toutEffacer();
    });

    // ----- Carte : zoom, panoramique, encadré de survol -----------------
    var svg = document.getElementById('carte');
    if (svg) {
      var W = parseFloat(svg.getAttribute('data-w'));
      var H = parseFloat(svg.getAttribute('data-h'));
      var vue = {x: 0, y: 0, w: W, h: H};
      var ZMAX = 14;                 // au-delà, les tracés se pixellisent
      var points = Array.prototype.slice.call(
        svg.querySelectorAll('.point'));
      var bases = points.map(function (c) {
        return parseFloat(c.getAttribute('r'));
      });
      var cibles = Array.prototype.slice.call(svg.querySelectorAll('.cible'));
      var baseCibles = cibles.map(function (c) {
        return parseFloat(c.getAttribute('r'));
      });

      function appliquer() {
        svg.setAttribute('viewBox',
          vue.x.toFixed(1) + ' ' + vue.y.toFixed(1) + ' ' +
          vue.w.toFixed(1) + ' ' + vue.h.toFixed(1));
        // Les rayons sont exprimés dans le repère de la carte : sans
        // compensation, un point deviendrait un disque en zoomant.
        var k = vue.w / W;
        points.forEach(function (c, i) {
          c.setAttribute('r', (bases[i] * k).toFixed(2));
        });
        cibles.forEach(function (c, i) {
          c.setAttribute('r', (baseCibles[i] * k).toFixed(2));
        });
      }

      function borner() {
        vue.w = Math.min(W, Math.max(W / ZMAX, vue.w));
        vue.h = vue.w * H / W;
        vue.x = Math.min(W - vue.w, Math.max(0, vue.x));
        vue.y = Math.min(H - vue.h, Math.max(0, vue.y));
      }

      function zoomer(facteur, cx, cy) {
        var avant = vue.w;
        vue.w = avant / facteur;
        borner();
        var k = vue.w / avant;
        // Le point sous le curseur doit rester sous le curseur.
        vue.x = cx - (cx - vue.x) * k;
        vue.y = cy - (cy - vue.y) * k;
        borner();
        appliquer();
      }

      function versCarte(clientX, clientY) {
        var r = svg.getBoundingClientRect();
        return {
          x: vue.x + (clientX - r.left) / r.width * vue.w,
          y: vue.y + (clientY - r.top) / r.height * vue.h
        };
      }

      svg.addEventListener('wheel', function (e) {
        e.preventDefault();
        var p = versCarte(e.clientX, e.clientY);
        zoomer(e.deltaY < 0 ? 1.25 : 1 / 1.25, p.x, p.y);
      }, {passive: false});

      var bt = {zplus: 1.5, zmoins: 1 / 1.5};
      Object.keys(bt).forEach(function (id) {
        var b = document.getElementById(id);
        if (b) b.addEventListener('click', function () {
          zoomer(bt[id], vue.x + vue.w / 2, vue.y + vue.h / 2);
        });
      });
      var br = document.getElementById('zreset');
      if (br) br.addEventListener('click', function () {
        vue = {x: 0, y: 0, w: W, h: H}; appliquer();
      });

      // Glisser pour déplacer. Un déplacement annule le clic, sinon on
      // filtrerait un pays chaque fois qu'on bouge la carte.
      var tire = null, bouge = false;
      svg.addEventListener('pointerdown', function (e) {
        if (e.pointerType === 'touch' && e.isPrimary === false) return;
        tire = {sx: e.clientX, sy: e.clientY, vx: vue.x, vy: vue.y};
        bouge = false;
        svg.classList.add('grab');
        svg.setPointerCapture(e.pointerId);
      });
      svg.addEventListener('pointermove', function (e) {
        if (!tire) return;
        var r = svg.getBoundingClientRect();
        var dx = (e.clientX - tire.sx) / r.width * vue.w;
        var dy = (e.clientY - tire.sy) / r.height * vue.h;
        if (Math.abs(e.clientX - tire.sx) + Math.abs(e.clientY - tire.sy) > 4) {
          bouge = true;
        }
        vue.x = tire.vx - dx; vue.y = tire.vy - dy;
        borner(); appliquer();
      });
      ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (ev) {
        svg.addEventListener(ev, function () {
          tire = null; svg.classList.remove('grab');
        });
      });

      // Pincement à deux doigts.
      var doigts = {}, ecart0 = null, w0 = null;
      svg.addEventListener('touchstart', function (e) {
        if (e.touches.length === 2) {
          ecart0 = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY);
          w0 = vue.w;
        }
      }, {passive: true});
      svg.addEventListener('touchmove', function (e) {
        if (e.touches.length === 2 && ecart0) {
          e.preventDefault();
          var d = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY);
          var cx = (e.touches[0].clientX + e.touches[1].clientX) / 2;
          var cy = (e.touches[0].clientY + e.touches[1].clientY) / 2;
          var p = versCarte(cx, cy);
          var avant = vue.w;
          vue.w = w0 * ecart0 / d;
          borner();
          var k = vue.w / avant;
          vue.x = p.x - (p.x - vue.x) * k;
          vue.y = p.y - (p.y - vue.y) * k;
          borner(); appliquer();
        }
      }, {passive: false});
      svg.addEventListener('touchend', function () { ecart0 = null; });

      // Encadré de survol.
      var bulle = document.getElementById('bulle');
      var bt2 = document.getElementById('bulle-t');
      var bs = document.getElementById('bulle-s');
      var bloc = document.getElementById('carte-bloc');
      function montrer(el, e) {
        if (!bulle || !el) return;
        bt2.innerHTML = el.getAttribute('data-titre') || '';
        bs.innerHTML = el.getAttribute('data-sous') || '';
        bulle.style.display = 'block';
        var r = bloc.getBoundingClientRect();
        var x = e.clientX - r.left + 14;
        var y = e.clientY - r.top + 14;
        if (x + bulle.offsetWidth > r.width - 8) {
          x = e.clientX - r.left - bulle.offsetWidth - 14;
        }
        if (y + bulle.offsetHeight > r.height - 8) {
          y = e.clientY - r.top - bulle.offsetHeight - 14;
        }
        bulle.style.left = Math.max(4, x) + 'px';
        bulle.style.top = Math.max(4, y) + 'px';
      }
      svg.addEventListener('mousemove', function (e) {
        var el = e.target.closest('[data-titre]');
        if (el) { montrer(el, e); } else if (bulle) {
          bulle.style.display = 'none';
        }
      });
      svg.addEventListener('mouseleave', function () {
        if (bulle) bulle.style.display = 'none';
      });

      // Sur une ville, le clic ouvre sa fiche plutôt que de filtrer.
      svg.addEventListener('click', function (e) {
        if (bouge) { bouge = false; return; }
        var v = e.target.closest('.ville');
        if (v && v.getAttribute('data-url')) {
          window.location.href = v.getAttribute('data-url');
        }
      });
    }

    // Carte : un clic sur un pays ou une ville filtre le tableau.
    var reset = document.getElementById('reset');
    function choisir(nom) {
      if (q) { q.value = nom; }
      document.querySelectorAll('.pays.actif').forEach(function (el) {
        el.classList.toggle('selection', el.getAttribute('data-pays') === nom);
      });
      if (reset) { reset.style.display = nom ? '' : 'none'; }
      apply();
      var t = document.querySelector('.search');
      if (t && nom) { t.scrollIntoView({behavior: 'smooth', block: 'start'}); }
    }
    document.querySelectorAll('.pays.actif[data-pays]').forEach(function (el) {
      el.addEventListener('click', function () {
        var nom = el.getAttribute('data-pays');
        choisir(el.classList.contains('selection') ? '' : nom);
      });
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.click(); }
      });
    });
    if (reset) { reset.addEventListener('click', function () { choisir(''); }); }
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

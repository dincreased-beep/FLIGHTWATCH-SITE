
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
        .normalize('NFD').replace(/[̀-ͯ]/g, '');
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

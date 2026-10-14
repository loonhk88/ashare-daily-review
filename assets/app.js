/* A股每日复盘 · 交互（零依赖） */
(function () {
  "use strict";

  // 回到顶部
  var top = document.getElementById("top");
  if (top) {
    var onScroll = function () {
      if (window.scrollY > 400) top.classList.add("show");
      else top.classList.remove("show");
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    top.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  // 导航滚动高亮
  var links = Array.prototype.slice.call(document.querySelectorAll(".nav a[href^='#']"));
  if (links.length) {
    var targets = links
      .map(function (a) {
        var el = document.querySelector(a.getAttribute("href"));
        return el ? { a: a, el: el } : null;
      })
      .filter(Boolean);

    var highlight = function () {
      var pos = window.scrollY + 130;
      var cur = null;
      targets.forEach(function (t) {
        if (t.el.offsetTop <= pos) cur = t;
      });
      links.forEach(function (a) { a.classList.remove("on"); });
      if (cur) cur.a.classList.add("on");
    };
    window.addEventListener("scroll", highlight, { passive: true });
    highlight();
  }

  // 表格横向滚动提示：可滚动时右侧显示渐变遮罩
  Array.prototype.forEach.call(document.querySelectorAll(".tw"), function (w) {
    var check = function () {
      // 已经滚到最右就不再提示
      var atEnd = w.scrollLeft + w.clientWidth >= w.scrollWidth - 4;
      if (w.scrollWidth > w.clientWidth + 4 && !atEnd) w.classList.add("scrollable");
      else w.classList.remove("scrollable");
    };
    check();
    w.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
  });
})();

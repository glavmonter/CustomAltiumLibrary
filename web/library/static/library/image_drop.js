// Зоны загрузки картинок (library.widgets.ImageDropWidget):
// перетаскивание файла, вставка из буфера обмена (Ctrl+V), выбор файла по клику.
// Выбранный файл кладётся в обычный <input type="file"> внутри зоны.
(function () {
  "use strict";

  const ACCEPTED = /^image\/(png|jpeg|webp|svg\+xml)$/;
  let lastActive = null;   // зона, с которой работали последней, — цель для Ctrl+V

  function zones() {
    return Array.from(document.querySelectorAll("[data-image-drop]"));
  }

  function setStatus(zone, text, isError) {
    const status = zone.querySelector(".image-drop__status");
    status.textContent = text;
    zone.classList.toggle("is-error", Boolean(isError));
  }

  function showPreview(zone, file, note) {
    const img = zone.querySelector(".image-drop__preview");
    if (img.src) URL.revokeObjectURL(img.src);
    img.src = URL.createObjectURL(file);
    img.hidden = false;
    zone.querySelector(".image-drop__reset").hidden = false;
    zone.classList.add("has-file");
    setStatus(zone, note || `${file.name} · ${Math.max(1, Math.round(file.size / 1024))} КБ — сохраните форму`);
  }

  function reset(zone) {
    const input = zone.querySelector("input[type=file]");
    const img = zone.querySelector(".image-drop__preview");
    input.value = "";
    if (img.src) URL.revokeObjectURL(img.src);
    img.removeAttribute("src");
    img.hidden = true;
    zone.querySelector(".image-drop__reset").hidden = true;
    zone.classList.remove("has-file");
    delete zone.dataset.source;
    setStatus(zone, "");
  }

  // source: "manual" — выбрал человек, "auto" — подставлено программно (ImageDrop.setFile)
  function acceptFile(zone, file, source = "manual", note = "") {
    if (!file) {
      setStatus(zone, "Картинка не найдена. Если перетаскиваете с веб-страницы — сохраните её как файл.", true);
      return;
    }
    if (!ACCEPTED.test(file.type)) {
      setStatus(zone, `Неподдерживаемый формат (${file.type || "неизвестен"}). Нужен PNG, JPEG, WebP или SVG.`, true);
      return;
    }
    const input = zone.querySelector("input[type=file]");
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    zone.dataset.source = source;
    showPreview(zone, file, note);
  }

  // API для других скриптов (library_path.js подставляет сгенерированное превью)
  window.ImageDrop = {
    /** Зона, в которой находится <input name="fieldName">. */
    zoneFor(fieldName) {
      const input = document.querySelector(`[data-image-drop] input[name="${fieldName}"]`);
      return input ? input.closest("[data-image-drop]") : null;
    },
    /** "manual" | "auto" | undefined — откуда картинка, выбранная сейчас (до сохранения). */
    source(zone) {
      return zone.dataset.source;
    },
    /** Есть ли у объекта уже сохранённая картинка. */
    hasCurrent(zone) {
      return zone.querySelector("input[type=file]").dataset.hasCurrent === "1";
    },
    setFile(zone, file, note) {
      acceptFile(zone, file, "auto", note);
    },
    reset,
  };

  function imageFromClipboard(event) {
    const items = event.clipboardData ? Array.from(event.clipboardData.items) : [];
    const item = items.find((i) => i.kind === "file" && i.type.startsWith("image/"));
    if (!item) return null;
    const file = item.getAsFile();
    const ext = file.type === "image/svg+xml" ? "svg" : file.type.split("/")[1].replace("jpeg", "jpg");
    // у вставленной картинки имя обычно «image.png» — делаем понятнее
    return new File([file], `clipboard-${Date.now()}.${ext}`, {type: file.type});
  }

  function pasteTarget() {
    const focused = document.activeElement && document.activeElement.closest("[data-image-drop]");
    if (focused) return focused;
    const all = zones();
    if (all.length === 1) return all[0];
    return lastActive;
  }

  function init(zone) {
    if (zone.dataset.imageDropReady) return;
    zone.dataset.imageDropReady = "1";
    const input = zone.querySelector("input[type=file]");
    const activate = () => { lastActive = zone; };

    zone.addEventListener("click", (event) => {
      activate();
      if (event.target === input || event.target.closest(".image-drop__reset")) return;
      input.click();
    });
    zone.addEventListener("keydown", (event) => {
      if (event.target === zone && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        input.click();
      }
    });
    zone.addEventListener("focus", activate);
    zone.addEventListener("pointerenter", activate);
    zone.querySelector(".image-drop__reset").addEventListener("click", (event) => {
      event.stopPropagation();
      reset(zone);
      zone.focus();
    });
    input.addEventListener("change", () => {
      if (input.files.length) acceptFile(zone, input.files[0]);
    });

    let depth = 0;   // dragenter/dragleave приходят и от дочерних элементов
    zone.addEventListener("dragenter", (event) => {
      event.preventDefault();
      depth += 1;
      zone.classList.add("is-dragover");
    });
    zone.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    });
    zone.addEventListener("dragleave", () => {
      depth = Math.max(0, depth - 1);
      if (!depth) zone.classList.remove("is-dragover");
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      depth = 0;
      zone.classList.remove("is-dragover");
      activate();
      acceptFile(zone, event.dataTransfer.files[0]);
    });
  }

  document.addEventListener("paste", (event) => {
    const zone = pasteTarget();
    if (!zone) return;
    const file = imageFromClipboard(event);
    if (!file) return;   // текст вставляется как обычно
    event.preventDefault();
    acceptFile(zone, file);
    zone.focus();
  });

  // файл, брошенный мимо зоны, браузер открыл бы вместо страницы с формой
  ["dragover", "drop"].forEach((type) => {
    window.addEventListener(type, (event) => {
      const isFile = event.dataTransfer && Array.from(event.dataTransfer.types).includes("Files");
      const inZone = event.target.closest && event.target.closest("[data-image-drop]");
      if (isFile && !inZone) event.preventDefault();
    });
  });

  function initAll() {
    zones().forEach(init);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();

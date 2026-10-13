// Поля Library Path / Footprint Path (library.widgets.LibraryPathWidget).
//
// Принимают перетащенный файл .SchLib / .PcbLib, вставленный файл (Ctrl+C в проводнике → Ctrl+V)
// или текстовый путь и приводят его к виду «symbols/<Категория>/<ИМЯ>.SchLib» —
// относительно корня репозитория библиотеки (.DbLib). То же правило на сервере: library/paths.py.
//
// Браузер не сообщает странице полный путь перетащенного файла, только имя. Поэтому в Chrome/Edge
// можно один раз выбрать папку библиотеки (File System Access API) — тогда путь вычисляется точно.
(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  //  Разбор файла библиотеки — ЗАГЛУШКА
  // ---------------------------------------------------------------------------

  /**
   * ЗАГЛУШКА: найти в файле библиотеки Altium символы (.SchLib) или посадочные места (.PcbLib).
   *
   * Что должна делать настоящая реализация:
   *   1. прочитать файл: `const buf = await file.arrayBuffer()`;
   *   2. разобрать OLE Compound File (CFB) — формат .SchLib / .PcbLib;
   *   3. каждый символ / посадочное место — отдельное хранилище (storage) в корне CFB;
   *      служебные потоки (FileHeader, Storage, SectionKeys, Library…) пропустить;
   *      длинные имена (> 31 символа) восстановить из потока SectionKeys;
   *   4. вернуть имена найденных элементов.
   *
   * Пока, по соглашению «один элемент — один файл», возвращает имя файла без расширения.
   * Подменить можно, не трогая остальной код: `AltiumLibrary.analyzeLibraryFile = async (file, root) => …`.
   *
   * @param {File} file          перетащенный или вставленный файл
   * @param {"symbols"|"footprints"} root  что искать: символы или посадочные места
   * @returns {Promise<{names: string[], stub: boolean}>}  stub=true — результат не из содержимого файла
   */
  async function analyzeLibraryFile(file, root) {
    return {names: [file.name.replace(/\.[^.]+$/, "")], stub: true};
  }

  /**
   * Приводит путь к виду «<root>/…»: кавычки и file:// убираются, «\» → «/»,
   * всё до последней папки root (без учёта регистра) отрезается.
   * @returns {{path: string, cut: boolean}}  cut=false — папки root в пути нет
   */
  function normalizePath(raw, root) {
    let path = String(raw || "").trim();
    if (path.length >= 2 && path[0] === path[path.length - 1] && `"'`.includes(path[0])) {
      path = path.slice(1, -1).trim();
    }
    path = path.replace(/^file:\/*/i, "");
    let segments = path.replace(/\\/g, "/").split("/").filter((s) => s && s !== ".");
    const i = segments.map((s) => s.toLowerCase()).lastIndexOf(root);
    if (i >= 0) segments = [root, ...segments.slice(i + 1)];
    return {path: segments.join("/"), cut: i >= 0};
  }

  window.AltiumLibrary = Object.assign(window.AltiumLibrary || {}, {analyzeLibraryFile, normalizePath});

  // ---------------------------------------------------------------------------
  //  Папка библиотеки (File System Access API, Chrome/Edge, https или localhost)
  // ---------------------------------------------------------------------------
  const FS_SUPPORTED = window.isSecureContext && "showDirectoryPicker" in window
    && typeof DataTransferItem !== "undefined" && "getAsFileSystemHandle" in DataTransferItem.prototype;
  const DB_NAME = "altium-library", STORE = "handles", ROOT_KEY = "libraryRoot";

  function idb(mode, action) {
    return new Promise((resolve, reject) => {
      const open = indexedDB.open(DB_NAME, 1);
      open.onupgradeneeded = () => open.result.createObjectStore(STORE);
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const db = open.result;
        const tx = db.transaction(STORE, mode);
        const request = action(tx.objectStore(STORE));
        tx.oncomplete = () => { db.close(); resolve(request.result); };
        tx.onerror = () => { db.close(); reject(tx.error); };
      };
    });
  }
  const loadRoot = () => (FS_SUPPORTED ? idb("readonly", (s) => s.get(ROOT_KEY)).catch(() => null) : Promise.resolve(null));
  const saveRoot = (handle) => idb("readwrite", (s) => s.put(handle, ROOT_KEY));

  /** Путь файла относительно выбранной папки библиотеки (с её именем впереди) или null. */
  async function pathFromHandle(handlePromise) {
    if (!handlePromise) return {path: null, root: null};
    try {
      const [handle, root] = await Promise.all([handlePromise, loadRoot()]);
      if (!handle || !root) return {path: null, root};
      const segments = await root.resolve(handle);
      return {path: segments ? [root.name, ...segments].join("/") : null, root};
    } catch (e) {
      return {path: null, root: null};
    }
  }

  async function showRootNames() {
    const root = await loadRoot();
    document.querySelectorAll(".library-path__root-name").forEach((el) => {
      el.textContent = root ? root.name : "не выбрана";
    });
  }

  // ---------------------------------------------------------------------------
  //  Поле пути
  // ---------------------------------------------------------------------------
  const WORDS = {
    symbols: {one: "символ", few: "символа", many: "символов"},
    footprints: {one: "посадочное место", few: "посадочных места", many: "посадочных мест"},
  };

  function plural(n, w) {
    const n10 = n % 10, n100 = n % 100;
    if (n10 === 1 && n100 !== 11) return w.one;
    if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return w.few;
    return w.many;
  }

  function setup(widget) {
    if (widget.dataset.libraryPathReady) return;
    widget.dataset.libraryPathReady = "1";

    const root = widget.dataset.root;
    const otherRoot = root === "symbols" ? "footprints" : "symbols";
    const extension = widget.dataset.extension.toLowerCase();
    const input = widget.querySelector("input");
    const form = widget.closest("form");
    const refInput = form && form.querySelector(`[name="${widget.dataset.refField}"]`);
    const refLabelEl = refInput && form.querySelector(`label[for="${refInput.id}"]`);
    const refLabel = refLabelEl ? refLabelEl.textContent.replace(/:\s*$/, "").trim() : widget.dataset.refField;
    const status = widget.querySelector(".library-path__status");

    function report(messages) {
      status.replaceChildren(...messages.map(([level, text]) => {
        const line = document.createElement("div");
        line.className = `library-path__msg library-path__msg--${level}`;
        line.textContent = text;
        return line;
      }));
    }

    function setPath(path) {
      input.value = path;
      input.dispatchEvent(new Event("input", {bubbles: true}));
    }

    function checkPath(normalized, messages) {
      const lower = normalized.path.toLowerCase();
      if (!normalized.cut && lower.split("/").includes(otherRoot)) {
        messages.push(["warn", `Похоже, это путь к ${otherRoot}/, а поле ждёт ${root}/.`]);
      } else if (!normalized.cut) {
        messages.push(["warn", `В пути нет папки ${root}/ — проверьте, что файл лежит в репозитории библиотеки.`]);
      }
      if (lower && !lower.endsWith(extension)) {
        messages.push(["warn", `Ожидается файл ${widget.dataset.extension}.`]);
      }
    }

    async function acceptFile(file, handlePromise) {
      const messages = [];
      if (!file.name.toLowerCase().endsWith(extension)) {
        messages.push(["warn", `Ожидается файл ${widget.dataset.extension}, а получен «${file.name}».`]);
      }

      const resolved = await pathFromHandle(handlePromise);
      if (resolved.path) {
        const normalized = normalizePath(resolved.path, root);
        setPath(normalized.path);
        if (!normalized.cut) messages.push(["warn", `Файл не в папке ${root}/ библиотеки «${resolved.root.name}».`]);
      } else {
        // имя есть, папки нет: сохраняем прежнюю категорию из поля, если она была
        const current = normalizePath(input.value, root).path;
        const category = current.match(new RegExp(`^${root}/(.+)/[^/]+$`, "i"));
        const prefix = category ? `${root}/${category[1]}/` : `${root}/`;
        setPath(prefix + file.name);
        let hint = category
          ? `Браузер не сообщает папку файла — оставлена прежняя категория «${category[1]}», проверьте.`
          : `Браузер не сообщает папку файла — допишите категорию: ${root}/<Категория>/${file.name}.`;
        if (FS_SUPPORTED && !resolved.root) hint += " Или выберите папку библиотеки — тогда путь определится сам.";
        if (resolved.root) hint += ` Файл не внутри выбранной папки «${resolved.root.name}».`;
        messages.push(["warn", hint]);
        if (!category) {
          input.focus();
          input.setSelectionRange(root.length + 1, root.length + 1);
        }
      }

      try {
        const result = await window.AltiumLibrary.analyzeLibraryFile(file, root);
        const names = (result && result.names) || [];
        const words = WORDS[root];
        if (names.length >= 2) {
          messages.push(["warn", `В файле ${names.length} ${plural(names.length, words)}: ${names.join(", ")}. `
            + `Принято: один ${words.one} — один файл. ${refLabel} заполните вручную.`]);
        } else if (names.length === 0) {
          messages.push(["warn", `В файле не найдено ни одного: ${words.one}.`]);
        } else if (refInput && !refInput.value.trim()) {
          refInput.value = names[0];
          refInput.dispatchEvent(new Event("input", {bubbles: true}));
          messages.push(["ok", `${refLabel}: «${names[0]}»`
            + (result.stub ? " — взято из имени файла, проверьте." : ".")]);
        }
      } catch (e) {
        messages.push(["warn", `Не удалось разобрать файл: ${e.message || e}`]);
      }
      report(messages);
    }

    function acceptText(text) {
      const normalized = normalizePath(text, root);
      setPath(normalized.path);
      const messages = [];
      checkPath(normalized, messages);
      report(messages);
    }

    // ---- перетаскивание: файл из проводника или текст пути ----
    let depth = 0;
    const draggable = (e) => e.dataTransfer && Array.from(e.dataTransfer.types).some((t) => t === "Files" || t === "text/plain");
    widget.addEventListener("dragenter", (e) => {
      if (!draggable(e)) return;
      e.preventDefault();
      depth += 1;
      widget.classList.add("is-dragover");
    });
    widget.addEventListener("dragover", (e) => {
      if (!draggable(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    });
    widget.addEventListener("dragleave", () => {
      depth = Math.max(0, depth - 1);
      if (!depth) widget.classList.remove("is-dragover");
    });
    widget.addEventListener("drop", (e) => {
      e.preventDefault();
      depth = 0;
      widget.classList.remove("is-dragover");
      const item = Array.from(e.dataTransfer.items || []).find((i) => i.kind === "file");
      let handlePromise = null;
      try {   // вызывать синхронно, пока идёт событие drop
        if (item && FS_SUPPORTED) handlePromise = item.getAsFileSystemHandle();
      } catch (err) { handlePromise = null; }
      const file = e.dataTransfer.files[0];
      if (file) acceptFile(file, handlePromise);
      else acceptText(e.dataTransfer.getData("text/plain"));
    });

    // ---- вставка: файл (Ctrl+C в проводнике) или путь целиком ----
    input.addEventListener("paste", (e) => {
      const data = e.clipboardData;
      if (!data) return;
      const file = Array.from(data.files || []).find((f) => f.name.toLowerCase().endsWith(extension)) || data.files[0];
      if (file && !file.type.startsWith("image/")) {
        e.preventDefault();
        acceptFile(file, null);
        return;
      }
      const text = data.getData("text/plain");
      if (/[\\/]/.test(text)) {   // похоже на путь — заменяем значение целиком
        e.preventDefault();
        acceptText(text);
      }
    });

    // ---- ручной ввод: нормализуем при уходе с поля ----
    input.addEventListener("change", () => {
      const normalized = normalizePath(input.value, root);
      if (normalized.path !== input.value) input.value = normalized.path;
    });

    // ---- выбор папки библиотеки ----
    if (FS_SUPPORTED) {
      widget.querySelector(".library-path__root").hidden = false;
      widget.querySelector(".library-path__root-pick").addEventListener("click", async () => {
        try {
          const handle = await window.showDirectoryPicker({id: "altium-library", mode: "read"});
          await saveRoot(handle);
          await showRootNames();
          report([["ok", `Папка библиотеки: «${handle.name}». Теперь путь перетащенного файла определяется точно.`]]);
        } catch (e) {
          if (e.name !== "AbortError") report([["warn", `Не удалось выбрать папку: ${e.message || e}`]]);
        }
      });
    }
  }

  function init() {
    document.querySelectorAll("[data-library-path]").forEach(setup);
    if (FS_SUPPORTED) showRootNames();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

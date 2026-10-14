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
  //  Разбор файла библиотеки — на сервере (library/altium_files.py)
  // ---------------------------------------------------------------------------

  function csrfToken() {
    const field = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (field) return field.value;
    const cookie = document.cookie.split("; ").find((c) => c.startsWith("csrftoken="));
    return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
  }

  /**
   * Находит в файле библиотеки Altium символы (.SchLib) или посадочные места (.PcbLib)
   * и получает их SVG-превью. Файл отправляется на сервер телом запроса, сервер разбирает его и не сохраняет.
   * Подменить можно, не трогая остальной код: `AltiumLibrary.analyzeLibraryFile = async (file, root) => …`.
   *
   * @param {File} file          перетащенный или вставленный файл
   * @param {"symbols"|"footprints"} root  что ожидается: символы или посадочные места
   * @param {{onProgress?: function({phase: "upload"|"processing", loaded?: number, total?: number}),
   *          signal?: AbortSignal}} [options]  прогресс отправки и отмена
   * @returns {Promise<{names: string[], stub: boolean, warnings: string[],
   *                    previews: Object<string, {svg?: string, error?: string}>}>}  previews — SVG от pyaltiumlib
   * @throws {Error} с понятным текстом; error.fileProblem = true — виноват сам файл
   *                  (слишком большой, не библиотека Altium, не тот тип), иначе — сбой сети/сервера
   */
  /** Ошибка из-за самого файла (не тот, повреждён, слишком большой) — в отличие от сбоя сети/сервера. */
  function fileProblem(message) {
    return Object.assign(new Error(message), {fileProblem: true});
  }

  function analyzeLibraryFile(file, root, {onProgress, signal} = {}) {
    const widget = document.querySelector(`[data-library-path][data-root="${root}"]`)
      || document.querySelector("[data-library-path]");
    const maxBytes = Number(widget.dataset.maxBytes);
    if (maxBytes && file.size > maxBytes) {
      return Promise.reject(fileProblem(
        `файл ${(file.size / 1048576).toFixed(1)} МБ, допустимо до ${Math.round(maxBytes / 1048576)} МБ.`));
    }
    const progress = onProgress || (() => {});
    // XMLHttpRequest, а не fetch: только он сообщает, сколько байт уже отправлено
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${widget.dataset.analyzeUrl}?root=${encodeURIComponent(root)}`);
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.setRequestHeader("X-CSRFToken", csrfToken());
      xhr.upload.onprogress = (e) => progress({phase: "upload", loaded: e.loaded, total: e.lengthComputable ? e.total : file.size});
      xhr.upload.onload = () => progress({phase: "processing"});
      xhr.onerror = () => reject(new Error("соединение с сервером прервано (нет связи или сервер закрыл соединение)."));
      xhr.onabort = () => reject(Object.assign(new Error("загрузка отменена."), {aborted: true}));
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (e) { data = null; }
        if (xhr.status < 200 || xhr.status >= 300 || !data) {
          const message = (data && data.error) || `сервер ответил ${xhr.status}.`;
          // 400 — пустой файл, 413 — больше лимита, 422 — не библиотека Altium или не тот тип
          reject([400, 413, 422].includes(xhr.status) && data ? fileProblem(message) : new Error(message));
          return;
        }
        resolve({names: data.names || [], stub: false, warnings: data.warnings || [], previews: data.previews || {},
                 descriptions: data.descriptions || {}});
      };
      if (signal) {
        if (signal.aborted) { xhr.abort(); return; }
        signal.addEventListener("abort", () => xhr.abort(), {once: true});
      }
      xhr.send(file);
    });
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
    symbols: {one: "символ", few: "символа", many: "символов", oneItem: "один символ"},
    footprints: {one: "посадочное место", few: "посадочных места", many: "посадочных мест",
                 oneItem: "одно посадочное место"},
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

    // ---- блокировка сохранения формы, пока путь указывает на файл с несколькими элементами ----
    let rejectedPath = null;       // путь к отклонённому файлу, пока ошибка не исправлена
    let previousGoodPath = "";    // что было в поле до отклонённого файла
    // Блокировки формы: ключ → {widget, title}. Ключ — этот виджет (ошибка в файле) или busyKey (идёт проверка).
    const busyKey = {};
    function lock(key, title) {
      if (!form) return;
      const locks = form.libraryPathLocks || (form.libraryPathLocks = new Map());
      if (title) locks.set(key, {widget, title}); else locks.delete(key);
      const first = locks.values().next().value;
      form.querySelectorAll("input[type=submit], button[type=submit]").forEach((button) => {
        button.disabled = Boolean(first);
        button.title = first ? first.title : "";
      });
      if (!form.libraryPathGuard) {   // Enter в поле формы тоже отправляет её
        form.libraryPathGuard = true;
        form.addEventListener("submit", (event) => {
          const blocker = form.libraryPathLocks.values().next().value;
          if (blocker) {
            event.preventDefault();
            blocker.widget.scrollIntoView({block: "center"});
          }
        });
      }
    }
    function setBlocked(blocked) {
      widget.classList.toggle("has-error", blocked);
      lock(widget, blocked ? "Сохранение недоступно: исправьте ошибку в пути к файлу библиотеки" : null);
    }

    // ---- индикатор загрузки файла на сервер ----
    const progressBox = widget.querySelector(".library-path__progress");
    const progressBar = progressBox.querySelector("progress");
    const progressText = progressBox.querySelector(".library-path__progress-text");
    let currentUpload = null;      // AbortController текущей проверки
    let progressTimer = null;
    const megabytes = (bytes) => (bytes / 1048576).toLocaleString("ru-RU", {minimumFractionDigits: 1, maximumFractionDigits: 1});
    function startProgress(controller) {
      clearTimeout(progressTimer);
      progressBar.max = 100;
      progressBar.value = 0;
      progressText.textContent = "Загрузка файла…";
      // на быстром соединении индикатор не успевает мигнуть
      progressTimer = setTimeout(() => { progressBox.hidden = false; }, 200);
      progressBox.querySelector(".library-path__progress-cancel").onclick = () => controller.abort();
      lock(busyKey, "Идёт проверка файла — дождитесь окончания");
    }
    function showProgress({phase, loaded, total}) {
      if (phase === "upload" && total) {
        const percent = Math.min(100, Math.round(loaded / total * 100));
        progressBar.value = percent;
        progressText.textContent = `Загрузка: ${percent} % · ${megabytes(loaded)} из ${megabytes(total)} МБ`;
      } else if (phase === "processing") {
        progressBar.removeAttribute("value");   // неопределённый прогресс
        progressText.textContent = "Разбор и отрисовка на сервере…";
      }
    }
    function stopProgress() {
      clearTimeout(progressTimer);
      progressBox.hidden = true;
      lock(busyKey, null);
    }

    let rejectReason = null;       // "multi" — несколько элементов, "invalid" — неправильный файл
    function clearRejection() {
      if (rejectedPath === null) return;
      rejectedPath = null;
      rejectReason = null;
      setBlocked(false);
      status.querySelectorAll(".library-path__msg--error").forEach((line) => line.remove());
    }
    /** Файл не принят: путь к нему остаётся в поле, сохранение блокируется до исправления. */
    function reject(reason, text, previousPath) {
      if (reason !== "multi") forgetFile();   // превью многоэлементного файла нужны: Ref выберет элемент
      rejectedPath = input.value;
      rejectReason = reason;
      previousGoodPath = previousPath;
      setBlocked(true);
      report([["error", `${text} Сохранение заблокировано — перетащите другой файл или исправьте путь.`,
        {label: "Вернуть прежний путь", run: () => { setPath(previousPath); clearRejection(); }}]]);
    }

    // messages: [уровень, текст, необязательное действие {label, run}]
    function report(messages, append = false) {
      const lines = messages.map(([level, text, action]) => {
        const line = document.createElement("div");
        line.className = `library-path__msg library-path__msg--${level}`;
        line.textContent = text;
        if (action) {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = action.label;
          button.addEventListener("click", () => { action.run(); line.remove(); });
          line.append(" ", button);
        }
        return line;
      });
      if (append) status.append(...lines);
      else status.replaceChildren(...lines);
    }

    // ---- сгенерированные превью (pyaltiumlib на сервере) ----
    let previews = {};        // {имя: {svg} | {error}} из последнего разобранного файла
    let fileNames = [];       // имена элементов этого файла
    let descriptions = {};    // {имя: Description из файла}
    let lastPreviewName = null;
    function forgetFile() {
      previews = {};
      descriptions = {};
      fileNames = [];
      lastPreviewName = null;
    }

    // ---- Description элемента → поле «Описание» (если оно есть в форме) ----
    const descriptionInput = form && widget.dataset.descriptionField
      && form.querySelector(`[name="${widget.dataset.descriptionField}"]`);
    let descriptionAuto = null;   // текст, подставленный нами: его можно заменить при смене элемента
    if (descriptionInput) {
      descriptionInput.addEventListener("input", (event) => {
        if (event.isTrusted) descriptionAuto = null;   // человек правит сам — больше не трогаем
      });
    }

    /** Подставляет Description элемента name, не перезаписывая то, что человек ввёл сам. */
    function applyDescription(name, messages) {
      if (!descriptionInput) return;
      const text = descriptions[name];
      const current = descriptionInput.value.trim();
      if (!text) {
        // у элемента нет описания: убираем подставленное нами для предыдущего элемента
        if (descriptionAuto && current === descriptionAuto) {
          descriptionInput.value = "";
          descriptionAuto = null;
          messages.push(["info", `У «${name}» в файле нет описания.`]);
        }
        return;
      }
      if (current === text) return;
      const fill = () => {
        descriptionInput.value = text;
        descriptionAuto = text;
        descriptionInput.dispatchEvent(new Event("input", {bubbles: true}));
      };
      if (!current || current === descriptionAuto) {
        fill();
        messages.push(["ok", `Описание из файла: «${text}».`]);
      } else {
        messages.push(["info", "Описание уже заполнено — из файла не подставлено.",
          {label: "Подставить описание из файла", run: fill}]);
      }
    }
    const imageZone = () => widget.dataset.previewField && window.ImageDrop
      && window.ImageDrop.zoneFor(widget.dataset.previewField);

    /** Подставляет превью элемента name в зону картинки, не трогая выбранное вручную и сохранённое. */
    function applyPreview(name, messages) {
      const zone = imageZone();
      const preview = previews[name];
      if (!zone || !preview) return;
      if (preview.error) {
        messages.push(["warn", `Картинку для «${name}» сгенерировать не удалось: ${preview.error}. Выберите её вручную.`]);
        return;
      }
      const file = new File([preview.svg], `${name.replace(/[\\/:*?"<>|]/g, "_")}.svg`, {type: "image/svg+xml"});
      const note = `Сгенерировано из файла: «${name}» — сохраните форму или замените своей картинкой`;
      const use = {label: "Подставить сгенерированную", run: () => window.ImageDrop.setFile(zone, file, note)};
      const source = window.ImageDrop.source(zone);
      if (source === "manual") {
        messages.push(["info", "Картинка уже выбрана вручную — сгенерированная не подставлена.", use]);
      } else if (source !== "auto" && window.ImageDrop.hasCurrent(zone)) {
        messages.push(["info", `Для «${name}» сгенерирована картинка; сохранённая не заменена.`, use]);
      } else {
        window.ImageDrop.setFile(zone, file, note);
        messages.push(["ok", `Картинка сгенерирована из файла: «${name}».`]);
      }
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
      const previousPath = rejectedPath === null ? input.value : previousGoodPath;
      clearRejection();

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

      if (!file.name.toLowerCase().endsWith(extension)) {
        reject("invalid", `Неправильный файл: ожидается ${widget.dataset.extension}, а получен «${file.name}».`, previousPath);
        return;
      }

      if (currentUpload) currentUpload.abort();   // новый файл отменяет проверку предыдущего
      const controller = new AbortController();
      currentUpload = controller;
      startProgress(controller);
      let result;
      try {
        result = await window.AltiumLibrary.analyzeLibraryFile(file, root,
          {onProgress: showProgress, signal: controller.signal});
      } catch (e) {
        if (controller !== currentUpload) return;   // проверку сменил другой файл — он и сообщит
        currentUpload = null;
        stopProgress();
        if (e.fileProblem) {
          reject("invalid", `Неправильный файл: ${e.message}`, previousPath);
          return;
        }
        // сбой сети/сервера или отмена — файл не проверен, но и не признан неправильным
        messages.push(["warn", e.aborted ? "Проверка файла отменена — файл не проверен."
          : `Не удалось проверить файл: ${e.message || e}`]);
        report(messages);
        return;
      }
      if (controller !== currentUpload) return;
      currentUpload = null;
      stopProgress();

      try {
        const names = (result && result.names) || [];
        const words = WORDS[root];
        previews = (result && result.previews) || {};
        descriptions = (result && result.descriptions) || {};
        fileNames = names;
        lastPreviewName = null;
        ((result && result.warnings) || []).forEach((w) => messages.push(["warn", w]));
        const ref = refInput ? refInput.value.trim() : "";
        if (names.length >= 2) {
          // нужен файл ровно с одним элементом
          reject("multi", `В файле ${names.length} ${plural(names.length, words)}: ${names.join(", ")}. `
            + `Нужен файл с одним элементом: ${words.oneItem} — один файл. `
            + `Или впишите в ${refLabel} нужный элемент — его картинка подставится.`, previousPath);
          return;
        }
        if (names.length === 0) {
          reject("invalid", `Неправильный файл: в нём нет ни одного элемента (${words.many}).`, previousPath);
          return;
        }
        if (refInput && !refInput.value.trim()) {
          refInput.value = names[0];
          refInput.dispatchEvent(new Event("input", {bubbles: true}));
          messages.push(["ok", `${refLabel}: «${names[0]}»`
            + (result.stub ? " — взято из имени файла, проверьте." : ".")]);
        }
        const chosen = names.includes(ref) ? ref : (names.length === 1 ? names[0] : null);
        if (chosen) {
          applyDescription(chosen, messages);
          applyPreview(chosen, messages);
        }
      } catch (e) {
        messages.push(["warn", `Не удалось обработать ответ сервера: ${e.message || e}`]);
      }
      report(messages);
    }

    function acceptText(text) {
      clearRejection();
      forgetFile();   // путь указывает на другой файл — его содержимого мы не видели
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

    // ---- Ref, введённый вручную, при файле с несколькими элементами (картинка и описание элемента) ----
    // Правка Ref человеком снимает блокировку «несколько элементов» (указан конкретный элемент;
    // неправильный файл она не исправляет). Ошибка становится предупреждением, которое остаётся
    // на виду, пока поле работает с этим файлом; к нему — сообщение о картинке выбранного элемента.
    function multiNote() {
      const words = WORDS[root];
      return ["warn", `В файле ${fileNames.length} ${plural(fileNames.length, words)}: ${fileNames.join(", ")}. `
        + `Принято: ${words.oneItem} — один файл; используется элемент, указанный в ${refLabel}.`];
    }

    function refMessages(extra) {
      return fileNames.length > 1 ? [multiNote(), ...extra] : extra;
    }

    if (refInput) {
      refInput.addEventListener("input", (event) => {
        if (!event.isTrusted) return;
        const unblocked = rejectReason === "multi";
        if (unblocked) clearRejection();
        const name = refInput.value.trim();
        const messages = [];
        if (name !== lastPreviewName && (previews[name] || descriptions[name])) {
          lastPreviewName = name;
          applyDescription(name, messages);
          applyPreview(name, messages);
        }
        if (unblocked || messages.length) report(refMessages(messages));
      });
      refInput.addEventListener("change", () => {
        const name = refInput.value.trim();
        // пока действует ошибка, её не трогаем: имена файла в ней уже перечислены
        // (Enter в поле тоже вызывает change)
        if (rejectedPath !== null) return;
        if (fileNames.length > 1 && name && !fileNames.includes(name)) {
          report(refMessages([["warn", `«${name}» нет в файле. В нём: ${fileNames.join(", ")}.`]]));
        }
      });
    }

    // ---- ручная правка пути снимает ошибку (синтетические события от setPath не в счёт) ----
    input.addEventListener("input", (event) => {
      if (event.isTrusted && rejectedPath !== null && input.value.trim() !== rejectedPath) clearRejection();
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

(() => {
  const UNIDADES = {
    cero: 0,
    uno: 1,
    una: 1,
    dos: 2,
    tres: 3,
    cuatro: 4,
    cinco: 5,
    seis: 6,
    siete: 7,
    ocho: 8,
    nueve: 9,
  };

  const DECENAS = {
    veinte: 20,
    treinta: 30,
    cuarenta: 40,
    cincuenta: 50,
    sesenta: 60,
    setenta: 70,
    ochenta: 80,
    noventa: 90,
  };

  const NUMEROS = {
    ...UNIDADES,
    diez: 10,
    once: 11,
    doce: 12,
    trece: 13,
    catorce: 14,
    quince: 15,
    dieciseis: 16,
    diecisiete: 17,
    dieciocho: 18,
    diecinueve: 19,
    ...DECENAS,
    veintiuno: 21,
    veintidos: 22,
    veintitres: 23,
    veinticuatro: 24,
    veinticinco: 25,
    veintiseis: 26,
    veintisiete: 27,
    veintiocho: 28,
    veintinueve: 29,
    cien: 100,
    ciento: 100,
  };

  const MULETILLAS = new Set([
    "a",
    "al",
    "de",
    "del",
    "el",
    "la",
    "los",
    "las",
    "en",
    "le",
    "lo",
    "sku",
    "skus",
    "codigo",
    "producto",
    "caja",
    "cajas",
    "unidad",
    "unidades",
    "seleccionado",
    "seleccionada",
    "ese",
    "esa",
    "este",
    "esta",
  ]);

  const WAKE_ALIASES = ["oye al", "oye aele", "oye ale", "oye a l", "hey al", "ok al", "okay al"];
  const LS_INVENTARIO = "al_inventario_activo";
  const LS_COMANDOS = "al_comandos_voz";
  const LS_HISTORIAL = "historialContenedores";
  const CATALOGO_COMANDOS = [
    { tipo: "SUMAR", titulo: "Sumar cajas", ejemplo: "suma [X]" },
    { tipo: "ESTATUS", titulo: "Consultar resumen", ejemplo: "estatus / status" },
    { tipo: "BUSCAR", titulo: "Seleccionar producto", ejemplo: "al [sufijo]" },
    { tipo: "EDITAR", titulo: "Fijar / editar conteo", ejemplo: "edita [X]" },
    { tipo: "PENDIENTES_SKU", titulo: "SKUs pendientes", ejemplo: "cuántos SKUs faltan" },
    { tipo: "PENDIENTES_CAJAS", titulo: "Cajas pendientes", ejemplo: "cuántas cajas faltan" },
    { tipo: "PALETAS", titulo: "Paletas del SKU", ejemplo: "cuántas paletas van" },
  ];
  const CONFIG_LOCAL = {
    wake_word: "oye al",
    sufijo_default: 2,
    idioma: "es-ES",
    confianza_minima: 0.55,
    longitud_minima: 2,
    comandos: {
      BUSCAR: ["al", "buscar", "busca", "encontrar", "ubica", "dame"],
      SUMAR: ["suma", "sumale", "agrega", "ponle", "van"],
      EDITAR: ["edita", "cambia", "fija en", "reemplaza"],
      PENDIENTES_SKU: ["cuantos skus faltan", "skus pendientes"],
      PENDIENTES_CAJAS: ["cuantas cajas faltan", "resto del contenedor", "cajas faltantes"],
      PALETAS: ["cuantas paletas van", "cuantas paletas", "paletas van", "cuantas paletas llevo"],
      ESTATUS: ["estatus", "status", "estado del contenedor", "como vamos"],
    },
  };

  const state = {
    config: null,
    inventario: { contenedor: "", skus: [] },
    kpis: {},
    chat: [],
    skuActivo: null,
    filtro: "",
    listening: false,
    commandArmed: false,
    recognition: null,
    speaking: false,
    blocked: false,
    restartTimer: null,
    transcriptTimer: null,
    audioStream: null,
    cierreRegistrado: false,
    historialFecha: "",
    modoSumarHoja: false,
    ultimoCierre: null,
    vozDesbloqueada: false,
  };

  const $ = (id) => document.getElementById(id);

  function leerComandosVoz() {
    try {
      const raw = localStorage.getItem(LS_COMANDOS);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (!data || typeof data !== "object") return null;
      const limpio = {};
      Object.entries(data).forEach(([tipo, aliases]) => {
        if (!Array.isArray(aliases)) return;
        const frases = aliases.map((alias) => String(alias || "").trim()).filter(Boolean);
        if (frases.length) limpio[tipo] = frases;
      });
      return Object.keys(limpio).length ? limpio : null;
    } catch {
      return null;
    }
  }

  function comandosPorDefecto() {
    const merged = { ...CONFIG_LOCAL.comandos };
    const extra = (state.config && state.config.comandos) || {};
    Object.entries(extra).forEach(([tipo, aliases]) => {
      const frases = [...(merged[tipo] || []), ...(aliases || [])]
        .map((alias) => String(alias || "").trim())
        .filter(Boolean);
      merged[tipo] = [...new Set(frases)];
    });
    return merged;
  }

  function comandosActivos() {
    const base = comandosPorDefecto();
    const custom = leerComandosVoz();
    if (!custom) return base;
    return { ...base, ...custom };
  }

  function aplicarComandosPersonalizados() {
    if (!state.config) state.config = { ...CONFIG_LOCAL };
    state.config.comandos = comandosActivos();
  }

  function parsearFrasesCampo(texto) {
    return String(texto || "")
      .split(/[,;\n]+/)
      .map((frase) => frase.trim())
      .filter(Boolean);
  }

  function abrirAjustesComandos() {
    const overlay = $("settings-overlay");
    const lista = $("settings-command-list");
    const status = $("settings-status");
    if (!overlay || !lista) return;
    const actuales = comandosActivos();
    lista.innerHTML = CATALOGO_COMANDOS.map((item) => {
      const frases = (actuales[item.tipo] || []).join(", ");
      return `<article class="settings-card">
        <h3>${escapar(item.titulo)}</h3>
        <p class="settings-example">Por defecto: ${escapar(item.ejemplo)}</p>
        <textarea id="cmd-${item.tipo}" data-tipo="${item.tipo}" spellcheck="false">${escapar(frases)}</textarea>
      </article>`;
    }).join("");
    if (status) status.textContent = "";
    overlay.classList.remove("hidden");
  }

  function cerrarAjustesComandos() {
    const overlay = $("settings-overlay");
    if (overlay) overlay.classList.add("hidden");
  }

  function guardarComandosVoz() {
    const lista = $("settings-command-list");
    const status = $("settings-status");
    if (!lista) return;
    const guardado = {};
    lista.querySelectorAll("textarea[data-tipo]").forEach((campo) => {
      const frases = parsearFrasesCampo(campo.value);
      if (frases.length) guardado[campo.dataset.tipo] = frases;
    });
    try {
      localStorage.setItem(LS_COMANDOS, JSON.stringify(guardado));
    } catch (error) {
      if (status) status.textContent = "No se pudieron guardar los comandos en el teléfono.";
      return;
    }
    aplicarComandosPersonalizados();
    if (status) status.textContent = "Comandos guardados. Ya están activos en el reconocimiento.";
  }

  function fraseEnTexto(texto, alias) {
    const a = normalizar(alias);
    if (!a) return false;
    const escaped = a.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(?:^|\\s)${escaped}(?:$|\\s)`).test(` ${texto} `);
  }

  function mejorAlias(texto, comandos) {
    let mejor = null;
    Object.entries(comandos || {}).forEach(([tipo, aliases]) => {
      (aliases || []).forEach((alias) => {
        const a = normalizar(alias);
        if (!a || !fraseEnTexto(texto, a)) return;
        if (!mejor || a.length > mejor.alias.length) mejor = { tipo, alias: a };
      });
    });
    return mejor;
  }

  function persistirInventario() {
    try {
      localStorage.setItem(
        LS_INVENTARIO,
        JSON.stringify({
          inventario: state.inventario,
          skuActivo: state.skuActivo,
          guardado_en: new Date().toISOString(),
        })
      );
    } catch (error) {
      console.log("[AL] No se pudo guardar en localStorage", error);
    }
  }

  function leerInventarioLocal() {
    try {
      const raw = localStorage.getItem(LS_INVENTARIO);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (data && data.inventario && Array.isArray(data.inventario.skus)) return data;
      if (data && Array.isArray(data.skus)) return { inventario: data, skuActivo: data.sku_activo || null };
    } catch (error) {
      console.log("[AL] Inventario local ilegible", error);
    }
    return null;
  }

  function enteroNoNegativo(valor, fallback = 0) {
    const n = Number(String(valor ?? "").replace(/,/g, "").trim());
    if (!Number.isFinite(n) || n < 0) return fallback;
    return Math.floor(n);
  }

  function normalizarCodigo(valor) {
    return String(valor || "")
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, "");
  }

  function recalcularSku(item) {
    const esperado = enteroNoNegativo(item.cantidad_esperada);
    const contador = enteroNoNegativo(item.contador);
    const factor = enteroNoNegativo(item.cajas_por_paleta);
    item.cantidad_esperada = esperado;
    item.contador = contador;
    item.cajas_por_paleta = factor;
    item.discrepancia = Math.max(contador - esperado, 0);
    if (contador > esperado) item.estado = "exceso";
    else if (esperado > 0 && contador >= esperado) item.estado = "completado";
    else if (contador > 0) item.estado = "en_proceso";
    else item.estado = "pendiente";
    return item;
  }

  function normalizarSkuItem(raw) {
    const sku = String((raw && (raw.sku || raw.SKU || raw.Product || raw.producto)) || "").trim();
    const producto = String((raw && (raw.producto || raw.Product || raw.descripcion || raw.description || sku)) || "").trim();
    return recalcularSku({
      sku,
      producto: producto || sku,
      cantidad_esperada: enteroNoNegativo(
        raw && (raw.cantidad_esperada ?? raw.QTY ?? raw.qty ?? raw["Total Cases"] ?? raw["Exp Eaches"])
      ),
      contador: enteroNoNegativo(raw && (raw.contador ?? raw.counted ?? raw.cnt), 0),
      cajas_por_paleta: enteroNoNegativo(
        raw && (raw.cajas_por_paleta ?? raw.TiHi ?? raw.pallet_factor),
        0
      ),
    });
  }

  function inventarioVacio() {
    return { contenedor: "", formato: "", fecha_carga: null, skus: [], hojasProcesadas: 0 };
  }

  function hojasDelContenedor(inventario) {
    const data = inventario || state.inventario || inventarioVacio();
    const n = enteroNoNegativo(data.hojasProcesadas);
    if (n > 0) return n;
    return (data.skus || []).length ? 1 : 0;
  }

  function asegurarHojas(inventario) {
    const data = inventario || inventarioVacio();
    if (!Array.isArray(data.skus)) data.skus = [];
    data.hojasProcesadas = hojasDelContenedor(data);
    return data;
  }

  function fusionarHojaAlContenedor(nueva) {
    const incoming = nueva || inventarioVacio();
    const actual = state.inventario || inventarioVacio();
    if (!(actual.skus || []).length) {
      return asegurarHojas({
        contenedor: incoming.contenedor || "",
        formato: incoming.formato || actual.formato || "",
        fecha_carga: incoming.fecha_carga || new Date().toISOString().slice(0, 19),
        skus: (incoming.skus || []).map(normalizarSkuItem).filter((item) => item.sku),
        hojasProcesadas: 1,
      });
    }
    if (!Array.isArray(actual.skus)) actual.skus = [];
    const mapa = new Map();
    actual.skus.forEach((item) => {
      const key = normalizarCodigo(item.sku);
      if (key) mapa.set(key, item);
    });
    (incoming.skus || []).forEach((raw) => {
      const item = normalizarSkuItem(raw);
      const key = normalizarCodigo(item.sku);
      if (!key) return;
      const exist = mapa.get(key);
      if (exist) {
        exist.cantidad_esperada += enteroNoNegativo(item.cantidad_esperada);
        exist.contador += enteroNoNegativo(item.contador);
        if (!enteroNoNegativo(exist.cajas_por_paleta) && enteroNoNegativo(item.cajas_por_paleta)) {
          exist.cajas_por_paleta = enteroNoNegativo(item.cajas_por_paleta);
        }
        recalcularSku(exist);
      } else {
        actual.skus.push(item);
        mapa.set(key, item);
      }
    });
    if (!actual.contenedor && incoming.contenedor) actual.contenedor = incoming.contenedor;
    actual.hojasProcesadas = hojasDelContenedor(actual) + 1;
    return actual;
  }

  function leerHistorialContenedores() {
    try {
      const raw = localStorage.getItem(LS_HISTORIAL);
      const data = raw ? JSON.parse(raw) : [];
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  }

  function persistirHistorialContenedores(lista) {
    localStorage.setItem(LS_HISTORIAL, JSON.stringify(lista));
  }

  function formatearFechaHora(fecha) {
    const d = fecha instanceof Date ? fecha : new Date(fecha);
    if (Number.isNaN(d.getTime())) return String(fecha || "");
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function fechaSoloDia(fechaStr) {
    return String(fechaStr || "").slice(0, 10);
  }

  function normalizarRegistroCierre(row) {
    if (!row || typeof row !== "object") return null;
    return {
      fecha: row.fecha || row.fecha_hora || "",
      contenedor: row.contenedor || row.numero_contenedor || "SIN-ID",
      totalSkus: enteroNoNegativo(row.totalSkus ?? row.total_skus),
      totalCajas: enteroNoNegativo(row.totalCajas ?? row.total_cajas),
      paletasCompletas: enteroNoNegativo(row.paletasCompletas ?? row.total_paletas_completas),
      paletasParciales: enteroNoNegativo(row.paletasParciales ?? row.total_paletas_parciales),
      hojasProcesadas: Math.max(1, enteroNoNegativo(row.hojasProcesadas ?? row.hojas_procesadas, 1)),
    };
  }

  function construirRegistroCierre() {
    const kpis = calcularKpis(state.inventario);
    const skus = (state.inventario.skus || []).length;
    if (!skus) return null;
    return {
      fecha: formatearFechaHora(new Date()),
      contenedor: state.inventario.contenedor || "SIN-ID",
      totalSkus: kpis.skus_totales || skus,
      totalCajas: kpis.cajas_contadas || 0,
      paletasCompletas: kpis.paletas_completas || 0,
      paletasParciales: kpis.paletas_parciales || 0,
      hojasProcesadas: Math.max(1, hojasDelContenedor()),
    };
  }

  function esMismoCierre(a, b) {
    const x = normalizarRegistroCierre(a);
    const y = normalizarRegistroCierre(b);
    if (!x || !y) return false;
    return (
      x.contenedor === y.contenedor &&
      x.totalSkus === y.totalSkus &&
      x.totalCajas === y.totalCajas &&
      x.paletasCompletas === y.paletasCompletas &&
      x.paletasParciales === y.paletasParciales &&
      x.hojasProcesadas === y.hojasProcesadas
    );
  }

  function textoWhatsAppCierre(row) {
    const r = normalizarRegistroCierre(row) || construirRegistroCierre();
    if (!r) return "";
    return [
      "*AL — Cierre de contenedor*",
      `📅 Fecha: ${r.fecha}`,
      `📦 Contenedor: ${r.contenedor}`,
      `📄 Hojas procesadas: ${r.hojasProcesadas}`,
      `🔢 Total SKUs: ${r.totalSkus}`,
      `📦 Total cajas: ${r.totalCajas}`,
      `✅ Paletas completas: ${r.paletasCompletas}`,
      `⚠️ Paletas parciales: ${r.paletasParciales}`,
    ].join("\n");
  }

  function mostrarAvisoCopia() {
    const el = $("copy-toast");
    if (!el) return;
    el.textContent = "¡Reporte copiado al portapapeles!";
    el.classList.remove("hidden");
    if (state.toastTimer) clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => el.classList.add("hidden"), 2200);
  }

  async function copiarTextoWhatsApp(texto) {
    if (!texto) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(texto);
      } else {
        throw new Error("clipboard");
      }
      mostrarAvisoCopia();
    } catch {
      window.prompt("Copie el reporte y péguelo en WhatsApp:", texto);
    }
  }

  function registrarCierreContenedor() {
    const registro = construirRegistroCierre();
    if (!registro) return false;
    const historial = leerHistorialContenedores();
    const ultimo = historial[historial.length - 1];
    if (esMismoCierre(ultimo, registro)) {
      state.cierreRegistrado = true;
      return false;
    }
    historial.push(registro);
    persistirHistorialContenedores(historial);
    state.cierreRegistrado = true;
    return true;
  }

  function historialNormalizado() {
    return leerHistorialContenedores().map(normalizarRegistroCierre).filter(Boolean);
  }

  function diaActual() {
    return fechaSoloDia(formatearFechaHora(new Date()));
  }

  function cierresDeFecha(dia) {
    const clave = dia || state.historialFecha || diaActual();
    return historialNormalizado().filter((row) => fechaSoloDia(row.fecha) === clave);
  }

  function totalesCierres(lista) {
    return lista.reduce(
      (acc, row) => ({
        contenedores: acc.contenedores + 1,
        totalSkus: acc.totalSkus + enteroNoNegativo(row.totalSkus),
        totalCajas: acc.totalCajas + enteroNoNegativo(row.totalCajas),
        paletasCompletas: acc.paletasCompletas + enteroNoNegativo(row.paletasCompletas),
        paletasParciales: acc.paletasParciales + enteroNoNegativo(row.paletasParciales),
      }),
      { contenedores: 0, totalSkus: 0, totalCajas: 0, paletasCompletas: 0, paletasParciales: 0 }
    );
  }

  function textoResumenDia(dia) {
    const clave = dia || state.historialFecha || diaActual();
    const lista = cierresDeFecha(clave);
    if (!lista.length) return "";
    const tot = totalesCierres(lista);
    const detalle = lista.map((row, i) =>
      [
        `*#${i + 1} ${row.contenedor}*`,
        `Hora: ${String(row.fecha).slice(11) || row.fecha}`,
        `📄 Hojas procesadas: ${row.hojasProcesadas}`,
        `SKUs: ${row.totalSkus} · Cajas: ${row.totalCajas}`,
        `Paletas: ${row.paletasCompletas} completas · ${row.paletasParciales} parciales`,
      ].join("\n")
    );
    return [
      `*AL — Resumen del día ${clave}*`,
      `Contenedores procesados: ${tot.contenedores}`,
      "",
      ...detalle,
      "",
      "*Totales del día*",
      `🔢 SKUs: ${tot.totalSkus}`,
      `📦 Cajas: ${tot.totalCajas}`,
      `✅ Paletas completas: ${tot.paletasCompletas}`,
      `⚠️ Paletas parciales: ${tot.paletasParciales}`,
    ].join("\n");
  }

  function filaHistorialHtml(row, idx, numero) {
    const r = normalizarRegistroCierre(row);
    if (!r) return "";
    return `<article class="settings-card">
      <p class="muted">#${numero} · ${escapar(r.fecha)}</p>
      <h3>Contenedor ${escapar(r.contenedor)}</h3>
      <p>📄 Hojas procesadas: ${r.hojasProcesadas}</p>
      <p>${r.totalSkus} SKUs · ${r.totalCajas} cajas</p>
      <p>${r.paletasCompletas} paletas completas · ${r.paletasParciales} paletas parciales</p>
      <button type="button" class="btn-whatsapp" data-historial-idx="${idx}">📲 Copiar para WhatsApp</button>
    </article>`;
  }

  function renderSelectorFechas(historial) {
    const select = $("historial-fecha");
    if (!select) return;
    const dias = [];
    historial.forEach((row) => {
      const dia = fechaSoloDia(row.fecha);
      if (dia && !dias.includes(dia)) dias.push(dia);
    });
    const hoy = diaActual();
    if (!dias.includes(hoy)) dias.unshift(hoy);
    if (!state.historialFecha || !dias.includes(state.historialFecha)) {
      state.historialFecha = hoy;
    }
    select.innerHTML = dias
      .map((dia) => `<option value="${escapar(dia)}"${dia === state.historialFecha ? " selected" : ""}>${escapar(dia)}</option>`)
      .join("");
  }

  function renderHistorial() {
    const body = $("historial-lista");
    const contador = $("historial-contador");
    if (!body) return;
    const historial = historialNormalizado();
    renderSelectorFechas(historial);
    const dia = state.historialFecha || diaActual();
    const delDia = historial
      .map((row, idx) => ({ row, idx }))
      .filter((item) => fechaSoloDia(item.row.fecha) === dia);
    const esHoy = dia === diaActual();
    if (contador) {
      contador.textContent = esHoy
        ? `Contenedores procesados hoy: ${delDia.length}`
        : `Contenedores procesados el ${dia}: ${delDia.length}`;
    }
    if (!delDia.length) {
      body.innerHTML = `<p class="historial-empty">No hay contenedores registrados en esta fecha.</p>`;
      return;
    }
    body.innerHTML = delDia
      .map((item, numero) => filaHistorialHtml(item.row, item.idx, numero + 1))
      .join("");
    body.querySelectorAll("[data-historial-idx]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const registro = historial[Number(btn.dataset.historialIdx)];
        copiarTextoWhatsApp(textoWhatsAppCierre(registro));
      });
    });
  }

  function abrirHistorial() {
    const overlay = $("historial-overlay");
    const status = $("historial-status");
    if (status) status.textContent = "";
    renderHistorial();
    if (overlay) overlay.classList.remove("hidden");
  }

  function cerrarHistorial() {
    const overlay = $("historial-overlay");
    if (overlay) overlay.classList.add("hidden");
  }

  async function copiarResumenDia() {
    const status = $("historial-status");
    const texto = textoResumenDia(state.historialFecha || diaActual());
    if (!texto) {
      if (status) status.textContent = "No hay contenedores en esta fecha para copiar.";
      return;
    }
    await copiarTextoWhatsApp(texto);
    if (status) status.textContent = "¡Reporte copiado al portapapeles!";
  }

  function limpiarHistorialCierres() {
    if (!leerHistorialContenedores().length) return;
    if (!window.confirm("¿Deseas borrar todo el historial de cierres de esta jornada?")) return;
    persistirHistorialContenedores([]);
    renderHistorial();
    const status = $("historial-status");
    if (status) status.textContent = "Historial borrado.";
  }

  function resetearSesionContenedor() {
    state.inventario = inventarioVacio();
    state.skuActivo = null;
    state.filtro = "";
    state.cierreRegistrado = false;
    state.modoSumarHoja = false;
    state.kpis = calcularKpis(state.inventario);
    persistirInventario();
    const filtro = $("tabla-filtro");
    if (filtro) filtro.value = "";
    setCajasCampo(0);
    const paleta = $("paleta-input");
    if (paleta) paleta.value = "0";
    const panel = $("inventario-panel");
    if (panel) panel.classList.remove("needs-sku");
    renderKpis();
    renderTabla();
    renderContenedor();
  }

  function prepararSiguienteHoja() {
    desbloquearVozIos();
    state.modoSumarHoja = true;
    const hojas = hojasDelContenedor();
    const siguiente = (state.inventario.skus || []).length ? hojas + 1 : 1;
    responder(`Listo para sumar la hoja ${siguiente}. Tome o cargue la foto.`);
    const camara = $("file-input-camera");
    if (camara) camara.click();
  }

  async function cerrarContenedorManual() {
    if (!(state.inventario.skus || []).length) {
      await responder("No hay un contenedor abierto para cerrar.");
      return;
    }
    const ok = window.confirm("¿Cerrar este contenedor de forma definitiva y guardar el consolidado?");
    if (!ok) return;
    const kpis = calcularKpis(state.inventario);
    const mensaje = mensajeCierreDescarga(kpis);
    state.ultimoCierre = construirRegistroCierre();
    registrarCierreContenedor();
    mostrarCompleto(true, mensaje);
    await responder(mensaje, { evento: "completo" });
    resetearSesionContenedor();
  }

  function calcularKpis(inventario) {
    const data = inventario || state.inventario || inventarioVacio();
    const skus = data.skus || [];
    const esperadas = skus.reduce((acc, item) => acc + enteroNoNegativo(item.cantidad_esperada), 0);
    const contadas = skus.reduce((acc, item) => acc + enteroNoNegativo(item.contador), 0);
    const cajasPendientes = skus.reduce(
      (acc, item) => acc + Math.max(enteroNoNegativo(item.cantidad_esperada) - enteroNoNegativo(item.contador), 0),
      0
    );
    const skusPendientes = skus.filter(
      (item) => enteroNoNegativo(item.contador) < enteroNoNegativo(item.cantidad_esperada)
    ).length;
    const avance = esperadas ? Math.round((Math.min(contadas, esperadas) / esperadas) * 1000) / 10 : 0;
    let paletasPendientes = 0;
    let paletasCompletas = 0;
    let paletasParciales = 0;
    skus.forEach((item) => {
      const factor = enteroNoNegativo(item.cajas_por_paleta);
      if (factor <= 0) return;
      const cajas = enteroNoNegativo(item.contador);
      if (cajas) {
        paletasCompletas += Math.floor(cajas / factor);
        if (cajas % factor) paletasParciales += 1;
      }
      const resto = Math.max(enteroNoNegativo(item.cantidad_esperada) - cajas, 0);
      if (resto) paletasPendientes += Math.ceil(resto / factor);
    });
    return {
      contenedor: data.contenedor || "",
      formato: data.formato || "",
      cajas_pendientes: cajasPendientes,
      skus_pendientes: skusPendientes,
      paletas_pendientes: paletasPendientes,
      paletas_completas: paletasCompletas,
      paletas_parciales: paletasParciales,
      paletas_sacadas: paletasCompletas + paletasParciales,
      paletas_definidas: skus.some((item) => enteroNoNegativo(item.cajas_por_paleta) > 0),
      avance,
      cajas_esperadas: esperadas,
      cajas_contadas: contadas,
      skus_totales: skus.length,
    };
  }

  function etiquetaCantidad(n, singular, plural) {
    const valor = enteroNoNegativo(n);
    return `${valor} ${valor === 1 ? singular : plural}`;
  }

  function mensajeCierreDescarga(kpis) {
    const metricas = kpis || calcularKpis(state.inventario);
    const cajas = etiquetaCantidad(metricas.cajas_contadas, "caja", "cajas");
    const hojas = hojasDelContenedor();
    const textoHojas = hojas ? ` Hojas procesadas: ${hojas}.` : "";
    if (metricas.paletas_definidas) {
      const completas = etiquetaCantidad(metricas.paletas_completas, "paleta completa", "paletas completas");
      const parciales = etiquetaCantidad(metricas.paletas_parciales, "paleta parcial", "paletas parciales");
      return (
        `¡Término de la descarga! El contenedor se ha descargado por completo. ` +
        `Se sacaron ${cajas}, ${completas} y ${parciales}.${textoHojas}`
      );
    }
    return `¡Término de la descarga! El contenedor se ha descargado por completo. Se sacaron ${cajas}. Las paletas no están definidas.${textoHojas}`;
  }

  function encontrarSku(sku) {
    const objetivo = normalizarCodigo(sku);
    return (state.inventario.skus || []).find((item) => normalizarCodigo(item.sku) === objetivo) || null;
  }

  function buscarPorSufijoLocal(dictado) {
    const codigo = normalizarCodigo(dictado);
    if (!codigo) {
      return {
        sufijo: "",
        coincidencias: [],
        total: 0,
        unica: false,
        requiere_desambiguacion: false,
        mensaje: "No se dictó ningún código.",
      };
    }
    const minimo = Number(state.config && state.config.sufijo_default) || 2;
    const sufijo = codigo.length >= minimo ? codigo : codigo;
    const hits = (state.inventario.skus || []).filter((item) => normalizarCodigo(item.sku).endsWith(sufijo));
    const total = hits.length;
    let mensaje = `Ningún SKU termina en ${sufijo}.`;
    if (total === 1) {
      const sku = hits[0];
      mensaje = `SKU ${sku.sku} confirmado. Esperadas ${sku.cantidad_esperada} cajas, contadas ${sku.contador}.`;
    } else if (total > 1) {
      mensaje = `Hay ${total} productos que terminan en ${sufijo}. Dicta un carácter más o selecciónalo en pantalla.`;
    }
    return {
      sufijo,
      coincidencias: hits,
      total,
      unica: total === 1,
      requiere_desambiguacion: total > 1,
      mensaje,
      contenedor: state.inventario.contenedor || "",
    };
  }

  function aplicarConteoLocal(sku, cantidad, modo) {
    if (cantidad < 0) throw new Error("La cantidad no puede ser negativa");
    const item = encontrarSku(sku);
    if (!item) throw new Error(`SKU ${sku} no está en la sesión`);
    const anterior = enteroNoNegativo(item.contador);
    if (modo === "sumar") item.contador = anterior + cantidad;
    else if (modo === "editar") item.contador = cantidad;
    else throw new Error("Modo inválido. Use sumar o editar.");
    recalcularSku(item);
    const kpis = calcularKpis(state.inventario);
    const exceso = enteroNoNegativo(item.discrepancia);
    let mensaje = `SKU ${item.sku}: ${item.contador} de ${item.cantidad_esperada} cajas.`;
    let alerta = null;
    if (exceso > 0) {
      alerta = `Atención: Discrepancia detectada. Exceso de ${exceso} cajas`;
      mensaje = `${alerta}. ${mensaje}`;
    }
    return {
      ok: true,
      accion: modo === "sumar" ? "suma" : "edicion",
      sku: item,
      alerta_discrepancia: alerta,
      mensaje,
      kpis,
      inventario: state.inventario,
    };
  }

  function actualizarPaletaLocal(sku, factor) {
    const item = encontrarSku(sku);
    if (!item) throw new Error(`SKU ${sku} no está en la sesión`);
    item.cajas_por_paleta = enteroNoNegativo(factor);
    recalcularSku(item);
    return {
      ok: true,
      sku: item,
      kpis: calcularKpis(state.inventario),
      inventario: state.inventario,
    };
  }

  function estatusLocal() {
    const kpis = calcularKpis(state.inventario);
    const completo = Boolean(kpis.skus_totales) && kpis.cajas_pendientes === 0;
    let mensaje = "No hay un contenedor cargado.";
    if (kpis.skus_totales && completo) {
      const hojas = hojasDelContenedor();
      mensaje =
        `No quedan cajas pendientes de las hojas actuales. ` +
        `Contenedor ${kpis.contenedor || "actual"}: ${kpis.cajas_contadas} cajas en ${kpis.skus_totales} SKUs` +
        `${hojas ? `, hoja ${hojas}` : ""}. Use Cerrar Contenedor cuando termine.`;
    } else if (kpis.skus_totales && !kpis.paletas_definidas) {
      mensaje = `Faltan ${kpis.skus_pendientes} SKUs por sacar y ${kpis.cajas_pendientes} cajas en total (paletas no definidas).`;
    } else if (kpis.skus_totales) {
      mensaje = `Faltan ${kpis.skus_pendientes} SKUs por sacar, ${kpis.cajas_pendientes} cajas en total y ${kpis.paletas_pendientes} paletas en total.`;
    }
    return { ...kpis, completo, mensaje, inventario: state.inventario };
  }

  function pendientesLocal() {
    const kpis = calcularKpis(state.inventario);
    return {
      ...kpis,
      mensaje_skus: `Faltan ${kpis.skus_pendientes} SKUs por completar.`,
      mensaje_cajas: `Faltan ${kpis.cajas_pendientes} cajas del contenedor ${kpis.contenedor || "actual"}.`,
    };
  }

  function detectarDelimitador(linea) {
    const comas = (linea.match(/,/g) || []).length;
    const puntos = (linea.match(/;/g) || []).length;
    return puntos > comas ? ";" : ",";
  }

  function parsearLineaCsv(linea, delimiter) {
    const out = [];
    let cur = "";
    let enComillas = false;
    for (let i = 0; i < linea.length; i += 1) {
      const ch = linea[i];
      if (ch === '"') {
        if (enComillas && linea[i + 1] === '"') {
          cur += '"';
          i += 1;
        } else {
          enComillas = !enComillas;
        }
      } else if (ch === delimiter && !enComillas) {
        out.push(cur.trim());
        cur = "";
      } else {
        cur += ch;
      }
    }
    out.push(cur.trim());
    return out;
  }

  function valorColumna(row, ...nombres) {
    const keys = Object.keys(row);
    for (const nombre of nombres) {
      const exacto = row[nombre];
      if (exacto != null && String(exacto).trim() !== "") return exacto;
      const key = keys.find((k) => k.toLowerCase() === String(nombre).toLowerCase());
      if (key && String(row[key] || "").trim() !== "") return row[key];
    }
    return "";
  }

  function parsearCsvInventario(texto) {
    const lineas = String(texto || "")
      .replace(/^\uFEFF/, "")
      .split(/\r?\n/)
      .filter((linea) => linea.trim());
    if (lineas.length < 2) return inventarioVacio();
    const delimiter = detectarDelimitador(lineas[0]);
    const headers = parsearLineaCsv(lineas[0], delimiter);
    const skus = [];
    let contenedor = "";
    for (let i = 1; i < lineas.length; i += 1) {
      const cols = parsearLineaCsv(lineas[i], delimiter);
      const row = {};
      headers.forEach((header, idx) => {
        row[header] = cols[idx] || "";
      });
      const sku = String(
        valorColumna(row, "sku", "SKU", "Product", "producto", "codigo") || ""
      ).trim();
      if (!sku) continue;
      if (!contenedor) {
        contenedor = String(
          valorColumna(row, "contenedor", "Trailer", "Other Reference Number") || ""
        ).trim();
      }
      skus.push(
        normalizarSkuItem({
          sku,
          producto: valorColumna(row, "producto", "Product", "descripcion", "description") || sku,
          cantidad_esperada: valorColumna(row, "cantidad_esperada", "QTY", "qty", "Total Cases", "Exp Eaches", "esperado"),
          contador: valorColumna(row, "contador", "counted", "cnt"),
          cajas_por_paleta: valorColumna(row, "cajas_por_paleta", "TiHi", "pallet_factor"),
        })
      );
    }
    return {
      contenedor,
      formato: "CSV",
      fecha_carga: new Date().toISOString().slice(0, 19),
      skus,
      hojasProcesadas: skus.length ? 1 : 0,
    };
  }

  function parsearJsonInventario(data) {
    let fuente = data;
    let skuActivo = null;
    if (data && data.inventario && Array.isArray(data.inventario.skus)) {
      fuente = data.inventario;
      skuActivo = data.skuActivo || data.sku_activo || null;
    } else if (Array.isArray(data)) {
      fuente = { contenedor: "", formato: "JSON", skus: data };
    } else if (!data || !Array.isArray(data.skus)) {
      throw new Error("El JSON no tiene una lista de SKUs.");
    }
    const inventario = {
      contenedor: String(fuente.contenedor || "").trim(),
      formato: fuente.formato || "JSON",
      fecha_carga: fuente.fecha_carga || new Date().toISOString().slice(0, 19),
      skus: (fuente.skus || []).map(normalizarSkuItem).filter((item) => item.sku),
      hojasProcesadas: enteroNoNegativo(fuente.hojasProcesadas ?? fuente.hojas_procesadas),
    };
    return { inventario, skuActivo };
  }

  function leerArchivoTexto(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error("No se pudo leer el archivo en el teléfono."));
      reader.readAsText(file, "UTF-8");
    });
  }

  function esArchivoJson(file) {
    const nombre = String(file && file.name ? file.name : "").toLowerCase();
    const tipo = String(file && file.type ? file.type : "").toLowerCase();
    return nombre.endsWith(".json") || tipo.includes("json");
  }

  function aplicarInventarioCargado(inventario, skuActivo, opciones = {}) {
    const restaurar = Boolean(opciones.restaurar);
    const acumular = !restaurar && ((state.inventario.skus || []).length > 0 || state.modoSumarHoja);
    const destino = acumular ? fusionarHojaAlContenedor(inventario) : asegurarHojas(inventario);
    (destino.skus || []).forEach(recalcularSku);
    state.inventario = destino;
    const existe = skuActivo && encontrarSku(skuActivo);
    state.skuActivo = existe ? existe.sku : null;
    state.kpis = calcularKpis(destino);
    state.cierreRegistrado = false;
    state.modoSumarHoja = false;
    persistirInventario();
    renderKpis();
    renderTabla();
    renderContenedor();
  }

  async function cargarInventarioArchivo(file) {
    const texto = await leerArchivoTexto(file);
    let inventario;
    let skuActivo = null;
    if (esArchivoJson(file)) {
      let parsedJson;
      try {
        parsedJson = JSON.parse(texto);
      } catch {
        throw new Error("El archivo JSON no es válido.");
      }
      const parsed = parsearJsonInventario(parsedJson);
      inventario = parsed.inventario;
      skuActivo = parsed.skuActivo;
    } else {
      inventario = parsearCsvInventario(texto);
    }
    if (!inventario.skus.length) {
      throw new Error("El archivo no contiene SKUs válidos.");
    }
    aplicarInventarioCargado(inventario, skuActivo);
    const hojas = hojasDelContenedor();
    const kpis = state.kpis || {};
    await responder(
      `Inventario local cargado. ${kpis.skus_totales || 0} SKUs y ${kpis.cajas_esperadas || 0} cajas esperadas` +
        `${state.inventario.contenedor ? ` en el contenedor ${state.inventario.contenedor}` : ""}` +
        `${hojas ? ` (Hoja ${hojas})` : ""}.`,
      { evento: "carga_local" }
    );
  }

  function construirExportacion() {
    (state.inventario.skus || []).forEach(recalcularSku);
    const kpis = calcularKpis(state.inventario);
    const estatus = estatusLocal();
    return {
      contenedor: state.inventario.contenedor || "",
      formato: state.inventario.formato || "",
      fecha_carga: state.inventario.fecha_carga || null,
      hojasProcesadas: hojasDelContenedor(),
      fecha_exportacion: new Date().toISOString(),
      sku_activo: state.skuActivo,
      kpis,
      estatus: { completo: estatus.completo, mensaje: estatus.mensaje },
      skus: state.inventario.skus || [],
    };
  }

  function nombreArchivoAvance() {
    const contenedor = String(state.inventario.contenedor || "sesion")
      .replace(/[^\w.-]+/g, "_")
      .replace(/^_+|_+$/g, "") || "sesion";
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    return `AL_avance_${contenedor}_${stamp}.json`;
  }

  async function exportarAvance() {
    if (!(state.inventario.skus || []).length) {
      await responder("No hay inventario para exportar. Cargue un archivo .csv o .json.");
      return;
    }
    const payload = construirExportacion();
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const nombre = nombreArchivoAvance();
    const archivo = new File([blob], nombre, { type: "application/json" });
    if (navigator.canShare && navigator.canShare({ files: [archivo] })) {
      try {
        await navigator.share({
          files: [archivo],
          title: "Avance AL",
          text: payload.estatus && payload.estatus.mensaje ? payload.estatus.mensaje : "Avance de contenedor",
        });
        await responder("Avance compartido. También queda en el teléfono.");
        return;
      } catch (error) {
        if (error && error.name === "AbortError") return;
      }
    }
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = nombre;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
    await responder("Avance exportado. Comparta el archivo .json por WhatsApp o correo.");
  }

  function idiomaReconocimiento() {
    const cfg = String((state.config && state.config.idioma) || "").trim();
    if (cfg === "es-ES" || cfg === "es-US") return cfg;
    return "es-ES";
  }

  function umbralConfianza() {
    const n = Number(state.config && state.config.confianza_minima);
    return Number.isFinite(n) ? n : 0.55;
  }

  function longitudMinima() {
    const n = Number(state.config && state.config.longitud_minima);
    return Number.isFinite(n) && n > 0 ? n : 2;
  }

  const FANTASMAS = new Set([
    "a",
    "e",
    "i",
    "o",
    "u",
    "un",
    "una",
    "de",
    "el",
    "la",
    "al",
    "en",
    "y",
    "uh",
    "um",
    "eh",
    "ah",
    "ay",
    "mm",
    "m",
    "n",
    "p",
    "t",
    "k",
    "s",
  ]);

  function pasaFiltrosVoz(texto, confidence) {
    const limpio = normalizar(texto);
    if (!limpio) return false;
    if (typeof confidence === "number" && confidence > 0 && confidence < umbralConfianza()) {
      console.log("[AL STT ruido] baja confianza", confidence.toFixed(2), limpio);
      return false;
    }
    const compacto = limpio.replace(/\s+/g, "");
    if (/\d/.test(compacto)) return true;
    if (compacto.length < longitudMinima()) {
      console.log("[AL STT ruido] demasiado corto", limpio);
      return false;
    }
    const palabras = limpio.split(" ").filter(Boolean);
    if (palabras.length === 1 && FANTASMAS.has(palabras[0])) {
      console.log("[AL STT ruido] frase fantasma", limpio);
      return false;
    }
    return true;
  }

  async function activarMicrofonoIndustrial() {
    if (state.audioStream && state.audioStream.active) return state.audioStream;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      console.log("[AL STT] getUserMedia no disponible; se usa el micrófono del reconocimiento");
      return null;
    }
    const constraints = {
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    };
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    state.audioStream = stream;
    const track = stream.getAudioTracks()[0];
    const settings = track && track.getSettings ? track.getSettings() : {};
    console.log("[AL STT] getUserMedia industrial", {
      echoCancellation: settings.echoCancellation !== false,
      noiseSuppression: settings.noiseSuppression !== false,
      autoGainControl: settings.autoGainControl !== false,
    });
    return stream;
  }

  function liberarMicrofono() {
    if (!state.audioStream) return;
    state.audioStream.getTracks().forEach((track) => track.stop());
    state.audioStream = null;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 403 && data.bloqueado) {
      bloquearLicencia(data.licencia || data);
      throw new Error(data.detail || "Licencia bloqueada");
    }
    if (!response.ok) {
      throw new Error(data.detail || "Error de red");
    }
    return data;
  }

  function appConfig() {
    return window.APP_CONFIG || {};
  }

  function fechaHoyISO() {
    const hoy = new Date();
    const y = hoy.getFullYear();
    const m = String(hoy.getMonth() + 1).padStart(2, "0");
    const d = String(hoy.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function licenciaClienteValida() {
    const cfg = appConfig();
    if (cfg.LICENCIA_ACTIVA !== true) return false;
    const exp = String(cfg.LICENCIA_EXPIRACION || "").trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(exp)) return false;
    return fechaHoyISO() <= exp;
  }

  function ocultarPanelTrabajo(ocultar) {
    const workspace = $("app-workspace");
    if (workspace) workspace.classList.toggle("hidden", Boolean(ocultar));
  }

  function pintarIdentidadCliente(activa) {
    const cfg = appConfig();
    const nombre = String(cfg.CLIENTE_NOMBRE || "").trim();
    const operador = String(cfg.CLIENTE_OPERADOR || "").trim();
    const tipo = String(cfg.LICENCIA_TIPO || "DEMO").trim() || "DEMO";
    const exp = String(cfg.LICENCIA_EXPIRACION || "").trim();
    const clientLabel = $("client-label");
    if (clientLabel) clientLabel.textContent = nombre || "";
    const chip = $("license-chip");
    if (chip) {
      chip.textContent = activa ? tipo : `${tipo} · vencida`;
      chip.className = activa ? "chip chip-ok" : "chip chip-bad";
    }
    const settingsNombre = $("settings-cliente-nombre");
    if (settingsNombre) settingsNombre.textContent = nombre || "Cliente";
    const settingsMeta = $("settings-cliente-meta");
    if (settingsMeta) {
      const partes = [tipo];
      if (operador) partes.push(`Operador: ${operador}`);
      if (exp) partes.push(`Vence ${exp}`);
      settingsMeta.textContent = partes.join(" · ");
    }
  }

  function bloquearLicencia(info) {
    state.blocked = true;
    ocultarPanelTrabajo(true);
    $("license-lock").classList.remove("hidden");
    $("license-lock-msg").textContent =
      (info && (info.error || info.detail)) ||
      "Licencia Expirada o Inválida. Por favor contacte al desarrollador para renovar su servicio.";
    pintarIdentidadCliente(false);
    stopMic();
  }

  function aplicarSesion(payload) {
    if (payload.inventario) state.inventario = asegurarHojas(payload.inventario);
    (state.inventario.skus || []).forEach(recalcularSku);
    state.kpis = payload.kpis || calcularKpis(state.inventario);
    persistirInventario();
    renderKpis();
    renderTabla();
    renderContenedor();
  }

  function skuActivoItem() {
    return (state.inventario.skus || []).find((row) => row.sku === state.skuActivo) || null;
  }

  function setCajasCampo(valor) {
    const campo = $("cajas-input");
    if (!campo) return;
    const n = Number(valor);
    campo.value = Number.isFinite(n) && n >= 0 ? String(Math.floor(n)) : "0";
  }

  function leerCajasCampo() {
    const n = Number($("cajas-input") && $("cajas-input").value);
    if (!Number.isFinite(n) || n < 0) return null;
    return Math.floor(n);
  }

  function pedirSeleccionSku() {
    const panel = $("inventario-panel");
    if (panel) {
      panel.classList.add("needs-sku");
      panel.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    responder("Selecciona un SKU en la tabla con un toque para aplicar el conteo.");
  }

  function desglosePaletas(item) {
    if (!item) {
      return {
        texto: "0 / 0 cajas",
        voz: "Primero selecciona un SKU.",
        factor: 0,
      };
    }
    const factor = Number(item.cajas_por_paleta) || 0;
    const cajas = Number(item.contador) || 0;
    const esperado = Number(item.cantidad_esperada) || 0;
    if (factor <= 0) {
      return {
        texto: `${cajas}/${esperado} cajas`,
        voz: `Este producto lleva ${cajas} de ${esperado} cajas.`,
        factor: 0,
      };
    }
    const completas = Math.floor(cajas / factor);
    const parcial = cajas % factor;
    const texto = parcial
      ? `${completas} Paletas completas | 1 Parcial (${parcial} cajas)`
      : `${completas} Paletas completas`;
    const voz = parcial
      ? `Llevas ${completas} paletas completas y 1 parcial de ${parcial} cajas para este producto.`
      : `Llevas ${completas} paletas completas y ninguna parcial para este producto.`;
    return { texto, voz, factor, completas, parcial };
  }

  function renderContenedor() {
    const id = state.inventario.contenedor || "Sin contenedor cargado";
    const hojas = hojasDelContenedor();
    const etiquetaHoja = hojas ? ` (Hoja ${hojas})` : "";
    $("container-label").textContent = state.inventario.contenedor
      ? `Contenedor Nº ${id}${etiquetaHoja}`
      : hojas
        ? `Contenedor sin número${etiquetaHoja}`
        : "Sin contenedor cargado";
    $("sku-activo-chip").textContent = state.skuActivo ? `SKU ${state.skuActivo}` : "SKU —";
    $("sku-activo-chip").className = state.skuActivo ? "chip chip-ok" : "chip chip-dim";
    const item = skuActivoItem();
    const label = $("count-sku-label");
    const meta = $("count-sku-meta");
    const breakdown = $("pallet-breakdown");
    const paleta = $("paleta-input");
    if (label) {
      label.textContent = item
        ? `${item.sku} · ${item.producto || ""}`
        : "Seleccione un SKU en la tabla";
    }
    if (meta) {
      meta.textContent = item ? `${item.contador} / ${item.cantidad_esperada}` : "0 / 0";
    }
    if (breakdown) {
      breakdown.textContent = desglosePaletas(item).texto;
    }
    if (paleta && document.activeElement !== paleta) {
      paleta.value = item ? String(Number(item.cajas_por_paleta) || 0) : "0";
    }
  }

  function renderKpis() {
    const k = state.kpis || {};
    $("kpi-cajas").textContent = k.cajas_pendientes ?? 0;
    $("kpi-skus").textContent = k.skus_pendientes ?? 0;
    $("kpi-avance").textContent = `${k.avance ?? 0}%`;
  }

  function etiquetaEstado(estado) {
    if (estado === "exceso") return "⚠️ Exceso";
    if (estado === "completado") return "Completado";
    if (estado === "en_proceso") return "En proceso";
    return "Pendiente";
  }

  function renderTabla() {
    const body = $("tabla-skus");
    const q = state.filtro.trim().toUpperCase();
    const rows = (state.inventario.skus || []).filter((item) => !q || String(item.sku).includes(q));
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="4" class="empty">Sin SKUs para mostrar.</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map((item) => {
        const active = state.skuActivo === item.sku ? "active" : "";
        return `<tr class="sku-row ${item.estado} ${active}" data-sku="${item.sku}" role="button" tabindex="0">
          <td><strong>${item.sku}</strong><br /><span class="muted">${item.producto || ""}</span></td>
          <td>${item.cantidad_esperada}</td>
          <td>${item.contador}${
            Number(item.cajas_por_paleta) > 0
              ? `<br /><span class="pallet-tag">${escapar(desglosePaletas(item).texto)}</span>`
              : `<br /><span class="muted">${item.contador}/${item.cantidad_esperada} cajas</span>`
          }</td>
          <td>${etiquetaEstado(item.estado)}</td>
        </tr>`;
      })
      .join("");
    body.querySelectorAll(".sku-row").forEach((row) => {
      row.addEventListener("click", () => seleccionarSku(row.dataset.sku, true));
    });
  }

  function renderChat() {
    const log = $("chat-log");
    log.innerHTML = state.chat
      .map((msg) => `<div class="bubble ${msg.rol}">${escapar(msg.texto)}</div>`)
      .join("");
    log.scrollTop = log.scrollHeight;
  }

  function escapar(texto) {
    return String(texto)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  async function limpiarChat() {
    state.chat = [];
    renderChat();
    try {
      await api("/api/chat", {
        method: "PUT",
        body: JSON.stringify({ mensajes: [] }),
      });
    } catch {
      /* el registro ya se vació en pantalla */
    }
  }

  async function pushChat(rol, texto, meta = {}) {
    state.chat.push({ rol, texto, meta });
    renderChat();
    try {
      await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({ rol, texto, meta }),
      });
    } catch {
      /* el historial local ya se ve en pantalla */
    }
  }

  function reanudarTrasTTS() {
    state.speaking = false;
    if (!state.listening || state.blocked) return;
    setMic(
      state.commandArmed ? "command" : "listen",
      state.commandArmed ? "Te escucho" : "Escuchando “Oye AL”"
    );
    reiniciarReconocimiento(180);
  }

  function desbloquearVozIos() {
    if (!window.speechSynthesis) return;
    try {
      window.speechSynthesis.getVoices();
      window.speechSynthesis.resume();
      const unlock = new SpeechSynthesisUtterance(" ");
      unlock.lang = idiomaReconocimiento();
      unlock.volume = 0.01;
      unlock.rate = 8;
      unlock.onend = () => {};
      unlock.onerror = () => {};
      window.speechSynthesis.speak(unlock);
      window.speechSynthesis.resume();
      state.vozDesbloqueada = true;
    } catch {
      /* iOS puede ignorar el primer intento; se reintenta en el siguiente toque */
    }
  }

  function enlazarDesbloqueoVoz(el) {
    if (!el) return;
    const unlock = () => desbloquearVozIos();
    el.addEventListener("pointerdown", unlock);
    el.addEventListener("click", unlock);
  }

  function hablar(texto) {
    if (!window.speechSynthesis) {
      reanudarTrasTTS();
      return;
    }
    state.speaking = true;
    pauseRecognition();
    try {
      window.speechSynthesis.cancel();
      window.speechSynthesis.resume();
    } catch {
      /* noop */
    }
    const utter = new SpeechSynthesisUtterance(texto);
    utter.lang = idiomaReconocimiento();
    utter.rate = 1.02;
    utter.volume = 1;
    utter.onend = reanudarTrasTTS;
    utter.onerror = reanudarTrasTTS;
    window.speechSynthesis.speak(utter);
    try {
      window.speechSynthesis.resume();
    } catch {
      /* noop */
    }
  }

  async function responder(texto, meta = {}) {
    await pushChat("al", texto, meta);
    hablar(texto);
  }

  function seleccionarSku(sku, anunciar = false) {
    state.skuActivo = sku;
    persistirInventario();
    const panel = $("inventario-panel");
    if (panel) panel.classList.remove("needs-sku");
    renderContenedor();
    renderTabla();
    $("sku-modal").classList.add("hidden");
    if (anunciar) {
      const item = (state.inventario.skus || []).find((row) => row.sku === sku);
      if (item) {
        responder(
          `SKU ${item.sku} seleccionado. Esperadas ${item.cantidad_esperada}, contadas ${item.contador}.`
        );
      }
    }
  }

  function mostrarCoincidencias(resultado) {
    $("sku-modal-title").textContent = `Hay ${resultado.total} productos que terminan en ${resultado.sufijo}`;
    $("sku-modal-sub").textContent = "Dicta un carácter más o selecciónalo en pantalla.";
    $("sku-modal-list").innerHTML = (resultado.coincidencias || [])
      .map(
        (item) => `<button type="button" class="sku-giant" data-sku="${item.sku}">
          <strong>${item.sku}</strong>
          <span>${item.producto || ""} · ${item.contador}/${item.cantidad_esperada}</span>
        </button>`
      )
      .join("");
    $("sku-modal-list").querySelectorAll(".sku-giant").forEach((btn) => {
      btn.addEventListener("click", () => seleccionarSku(btn.dataset.sku, true));
    });
    $("sku-modal").classList.remove("hidden");
  }

  function normalizar(texto) {
    return String(texto || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9ñ\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function convertirNumerosHablados(texto) {
    let t = normalizar(texto);
    t = t.replace(
      /\b(veinte|treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)\s+y\s+(uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve)\b/g,
      (_, decena, unidad) => String(DECENAS[decena] + UNIDADES[unidad])
    );
    Object.keys(NUMEROS)
      .sort((a, b) => b.length - a.length)
      .forEach((palabra) => {
        t = t.replace(new RegExp(`\\b${palabra}\\b`, "g"), String(NUMEROS[palabra]));
      });
    return t.replace(/\s+/g, " ").trim();
  }

  function quitarMuletillas(texto) {
    return normalizar(texto)
      .split(" ")
      .filter((palabra) => palabra && !MULETILLAS.has(palabra))
      .join(" ");
  }

  function extraerSufijoNumerico(texto) {
    const digitos = String(texto).match(/\d+/g);
    return digitos ? digitos.join("") : "";
  }

  function parsearCantidadYSufijo(resto) {
    const limpio = quitarMuletillas(convertirNumerosHablados(resto));
    const nums = String(limpio).match(/\d+/g) || [];
    if (!nums.length) return { cantidad: null, sufijo: "" };
    return {
      cantidad: Number(nums[0]),
      sufijo: nums.slice(1).join(""),
    };
  }

  function quitarWake(texto) {
    let t = normalizar(texto);
    for (const alias of WAKE_ALIASES) {
      if (t.startsWith(alias)) t = t.slice(alias.length).trim();
    }
    const cfgWake = normalizar((state.config && state.config.wake_word) || "oye al");
    if (t.startsWith(cfgWake)) t = t.slice(cfgWake.length).trim();
    return t;
  }

  function contieneWake(texto) {
    const t = normalizar(texto);
    const cfgWake = normalizar((state.config && state.config.wake_word) || "oye al");
    return t.includes(cfgWake) || WAKE_ALIASES.some((alias) => t.includes(alias));
  }

  function matchComando(texto) {
    const personalizados = leerComandosVoz();
    const hitCustom = mejorAlias(texto, personalizados);
    if (hitCustom) return hitCustom;
    return mejorAlias(texto, comandosPorDefecto());
  }

  async function buscarSufijo(dictado) {
    const data = buscarPorSufijoLocal(dictado);
    if (data.unica && data.coincidencias[0]) {
      seleccionarSku(data.coincidencias[0].sku);
      $("sku-modal").classList.add("hidden");
    } else if (data.requiere_desambiguacion) {
      mostrarCoincidencias(data);
    }
    await responder(data.mensaje, { sufijo: data.sufijo, total: data.total });
    return data;
  }

  async function aplicarConteo(modo, cantidad, sku) {
    const objetivo = sku || state.skuActivo;
    if (!objetivo) {
      pedirSeleccionSku();
      return;
    }
    setCajasCampo(cantidad);
    const data = aplicarConteoLocal(objetivo, cantidad, modo);
    aplicarSesion(data);
    state.skuActivo = data.sku.sku;
    persistirInventario();
    renderContenedor();
    await responder(data.mensaje, { sku: data.sku.sku, modo });
  }

  async function aplicarConteoConSufijo(modo, cantidad, sufijo) {
    setCajasCampo(cantidad);
    if (sufijo) {
      const found = await buscarSufijo(sufijo);
      if (!found.unica) return;
      await aplicarConteo(modo, cantidad, found.coincidencias[0].sku);
      return;
    }
    if (state.skuActivo) {
      await aplicarConteo(modo, cantidad, state.skuActivo);
      return;
    }
    pedirSeleccionSku();
  }

  async function guardarPaleta(factor) {
    if (!state.skuActivo) {
      pedirSeleccionSku();
      return;
    }
    const n = factor === "" || factor == null ? 0 : Number(factor);
    if (!Number.isFinite(n) || n < 0) {
      await responder("Indica un número válido de cajas por paleta, o 0 para desactivar.");
      return;
    }
    const data = actualizarPaletaLocal(state.skuActivo, Math.floor(n));
    aplicarSesion(data);
    state.skuActivo = data.sku.sku;
    renderContenedor();
    const info = desglosePaletas(data.sku);
    await responder(info.voz, { sku: data.sku.sku, evento: "paleta" });
  }

  async function reportarPaletas() {
    const item = skuActivoItem();
    if (!item) {
      pedirSeleccionSku();
      return;
    }
    const info = desglosePaletas(item);
    await responder(info.voz, { sku: item.sku, evento: "paletas" });
  }

  function mostrarCompleto(mostrar, mensaje) {
    const el = $("complete-alert");
    const msg = $("complete-alert-msg");
    if (mostrar && msg) msg.textContent = mensaje || mensajeCierreDescarga();
    if (el) el.classList.toggle("hidden", !mostrar);
  }

  function pintarEstatusModal(data) {
    const kpis = data || estatusLocal();
    const body = document.getElementById("contenido-estatus");
    if (!body) return;
    const hojas = hojasDelContenedor();
    const esperadas = enteroNoNegativo(kpis.cajas_esperadas);
    const contadas = enteroNoNegativo(kpis.cajas_contadas);
    const contenedor = kpis.contenedor || state.inventario.contenedor || "Sin contenedor";
    const cajas = esperadas ? `${contadas} / ${esperadas}` : String(contadas);
    body.innerHTML = [
      `<p><strong>Contenedor</strong><span>${contenedor}</span></p>`,
      `<p><strong>Hojas procesadas</strong><span>${hojas}</span></p>`,
      `<p><strong>SKUs</strong><span>${kpis.skus_totales || 0}</span></p>`,
      `<p><strong>Cajas</strong><span>${cajas}</span></p>`,
      `<p><strong>Paletas completas</strong><span>${kpis.paletas_completas || 0}</span></p>`,
      `<p><strong>Paletas parciales</strong><span>${kpis.paletas_parciales || 0}</span></p>`,
    ].join("");
  }

  function mostrarEstatusModal(mostrar) {
    const el = document.getElementById("modal-estatus");
    if (el) el.style.display = mostrar ? "flex" : "none";
  }

  function cerrarModalEstatus() {
    mostrarEstatusModal(false);
  }

  async function reportarEstatus() {
    desbloquearVozIos();
    const data = estatusLocal();
    aplicarSesion(data);
    pintarEstatusModal(data);
    const modal = document.getElementById("modal-estatus");
    if (modal) modal.style.display = "flex";
    await responder(data.mensaje, { evento: "estatus", completo: data.completo });
  }

  async function conteoManual(modo) {
    const cantidad = leerCajasCampo();
    if (cantidad === null) {
      await responder("Indica las cajas a procesar en el campo numérico.");
      return;
    }
    if (modo === "sumar" && cantidad === 0) {
      await responder("Indica cuántas cajas sumar. Use +1, +5 o +10, o dicta suma 15.");
      return;
    }
    if (!state.skuActivo) {
      pedirSeleccionSku();
      return;
    }
    await aplicarConteo(modo, cantidad, state.skuActivo);
  }

  async function procesarComando(raw) {
    const texto = convertirNumerosHablados(quitarWake(raw));
    if (!texto) {
      state.commandArmed = true;
      setMic("command", "Te escucho");
      await responder("Te escucho.");
      return;
    }

    await pushChat("operador", raw);
    const hit = matchComando(texto);
    const resto = hit ? texto.replace(hit.alias, " ").replace(/\s+/g, " ").trim() : texto;

    try {
      if (!hit) {
        const sufijo = extraerSufijoNumerico(quitarMuletillas(resto));
        if (sufijo) {
          await buscarSufijo(sufijo);
          return;
        }
        await responder("No reconocí el comando. Prueba con buscar, suma o edita.");
        return;
      }

      if (hit.tipo === "BUSCAR") {
        const sufijo = extraerSufijoNumerico(quitarMuletillas(resto));
        if (!sufijo) {
          await responder("No detecté dígitos del SKU. Dicta el sufijo numérico, por ejemplo: buscar 45.");
          return;
        }
        await buscarSufijo(sufijo);
        return;
      }

      if (hit.tipo === "SUMAR" || hit.tipo === "EDITAR") {
        const { cantidad, sufijo } = parsearCantidadYSufijo(resto);
        if (cantidad === null) {
          await responder("No entendí la cantidad. Dicta un número, por ejemplo: suma 15.");
          return;
        }
        await aplicarConteoConSufijo(hit.tipo === "SUMAR" ? "sumar" : "editar", cantidad, sufijo);
        return;
      }

      if (hit.tipo === "PENDIENTES_SKU" || hit.tipo === "PENDIENTES_CAJAS") {
        const data = pendientesLocal();
        aplicarSesion({ kpis: data, inventario: state.inventario });
        await responder(hit.tipo === "PENDIENTES_SKU" ? data.mensaje_skus : data.mensaje_cajas);
        return;
      }

      if (hit.tipo === "PALETAS") {
        await reportarPaletas();
        return;
      }

      if (hit.tipo === "ESTATUS") {
        await reportarEstatus();
        return;
      }
    } catch (error) {
      await responder(error.message || "No pude completar la orden.");
    } finally {
      if (texto) {
        state.commandArmed = false;
        if (state.listening && !state.speaking) setMic("listen", "Escuchando “Oye AL”");
      }
    }
  }

  function setMic(mode, label) {
    $("mic-light").className = `mic-light ${mode}`;
    $("mic-label").textContent = label;
    $("mic-fab").setAttribute("aria-pressed", state.listening ? "true" : "false");
  }

  function mostrarTranscripcion(texto, parcial) {
    const banner = $("live-transcript");
    const linea = $("live-transcript-text");
    if (!banner || !linea) return;
    const limpio = String(texto || "").trim();
    if (!limpio) return;
    linea.textContent = limpio;
    banner.classList.remove("hidden");
    console.log(parcial ? "[AL STT parcial]" : "[AL STT final]", limpio);
    if (state.transcriptTimer) clearTimeout(state.transcriptTimer);
    state.transcriptTimer = setTimeout(() => {
      banner.classList.add("hidden");
    }, parcial ? 1200 : 2800);
  }

  function pauseRecognition() {
    if (state.restartTimer) {
      clearTimeout(state.restartTimer);
      state.restartTimer = null;
    }
    if (state.recognition) {
      try {
        state.recognition.stop();
      } catch {
        /* noop */
      }
    }
  }

  function reiniciarReconocimiento(delayMs) {
    if (state.restartTimer) clearTimeout(state.restartTimer);
    state.restartTimer = setTimeout(() => {
      state.restartTimer = null;
      if (!state.listening || state.speaking || state.blocked) return;
      const rec = state.recognition;
      if (rec) {
        try {
          rec.start();
          setMic(state.commandArmed ? "command" : "listen", state.commandArmed ? "Te escucho" : "Escuchando “Oye AL”");
          return;
        } catch {
          /* InvalidStateError: ya activo o hay que recrear */
        }
      }
      startEngine();
    }, delayMs);
  }

  function startEngine() {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Ctor) {
      setMic("error", "Voz no soportada. Use Chrome o Edge.");
      return;
    }
    if (!state.audioStream || !state.audioStream.active) {
      activarMicrofonoIndustrial()
        .then(() => arrancarReconocimiento(Ctor))
        .catch(() => {
          setMic("error", "Permiso de micrófono denegado");
          state.listening = false;
        });
      return;
    }
    arrancarReconocimiento(Ctor);
  }

  function arrancarReconocimiento(Ctor) {
    if (state.recognition) {
      try {
        state.recognition.onend = null;
        state.recognition.onresult = null;
        state.recognition.stop();
      } catch {
        /* noop */
      }
    }
    const rec = new Ctor();
    rec.lang = idiomaReconocimiento();
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.onresult = (event) => {
      let parcial = "";
      let finalText = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const alt = event.results[i][0];
        const piece = (alt && alt.transcript) || "";
        const confidence = alt && typeof alt.confidence === "number" ? alt.confidence : null;
        if (!event.results[i].isFinal) {
          parcial += piece;
          continue;
        }
        if (!pasaFiltrosVoz(piece, confidence)) continue;
        finalText += piece;
      }
      if (parcial) mostrarTranscripcion(parcial, true);
      if (finalText) mostrarTranscripcion(finalText, false);
      if (!finalText || state.speaking) return;
      if (state.commandArmed || contieneWake(finalText)) {
        procesarComando(finalText);
      }
    };
    rec.onerror = (event) => {
      console.log("[AL STT error]", event.error);
      if (event.error === "not-allowed") {
        setMic("error", "Permiso de micrófono denegado");
        state.listening = false;
        liberarMicrofono();
        return;
      }
      if (event.error === "aborted" || event.error === "no-speech") return;
    };
    rec.onend = () => {
      if (!state.listening || state.blocked) return;
      if (state.speaking) return;
      console.log("[AL STT] onend → rearmando “Oye AL”");
      reiniciarReconocimiento(220);
    };
    state.recognition = rec;
    try {
      rec.start();
      setMic(state.commandArmed ? "command" : "listen", state.commandArmed ? "Te escucho" : "Escuchando “Oye AL”");
      console.log("[AL STT] motor activo", rec.lang, "umbral", umbralConfianza());
    } catch {
      reiniciarReconocimiento(320);
    }
  }

  function stopMic() {
    state.listening = false;
    state.commandArmed = false;
    if (state.restartTimer) {
      clearTimeout(state.restartTimer);
      state.restartTimer = null;
    }
    if (state.recognition) {
      try {
        state.recognition.onend = null;
        state.recognition.stop();
      } catch {
        /* noop */
      }
    }
    liberarMicrofono();
    const banner = $("live-transcript");
    if (banner) banner.classList.add("hidden");
    setMic("idle", "Toca para hablar");
  }

  function toggleMic() {
    if (state.blocked) return;
    if (state.listening) {
      stopMic();
      return;
    }
    state.listening = true;
    setMic("listen", "Activando micrófono…");
    startEngine();
  }

  const MAX_LADO_IMAGEN = 1280;
  const JPEG_CALIDAD = 0.7;

  function canvasABlob(canvas, type, quality) {
    return new Promise((resolve, reject) => {
      if (canvas.toBlob) {
        canvas.toBlob((blob) => {
          if (blob) resolve(blob);
          else reject(new Error("No se pudo comprimir la imagen."));
        }, type, quality);
        return;
      }
      try {
        const dataUrl = canvas.toDataURL(type, quality);
        const bin = atob((dataUrl.split(",")[1] || ""));
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
        resolve(new Blob([bytes], { type }));
      } catch (err) {
        reject(err);
      }
    });
  }

  function cargarImagenArchivo(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        resolve(img);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("No se pudo leer la imagen."));
      };
      img.src = url;
    });
  }

  async function comprimirImagenCliente(file) {
    const tipo = String(file && file.type ? file.type : "").toLowerCase();
    if (!file || (tipo && !tipo.startsWith("image/"))) return file;
    let fuente = null;
    let canvas = null;
    let ctx = null;
    try {
      if (typeof createImageBitmap === "function") {
        try {
          fuente = await createImageBitmap(file, { imageOrientation: "from-image" });
        } catch {
          fuente = await cargarImagenArchivo(file);
        }
      } else {
        fuente = await cargarImagenArchivo(file);
      }
      const w = fuente.naturalWidth || fuente.width;
      const h = fuente.naturalHeight || fuente.height;
      if (!w || !h) return file;
      const scale = Math.min(1, MAX_LADO_IMAGEN / Math.max(w, h));
      const tw = Math.max(1, Math.round(w * scale));
      const th = Math.max(1, Math.round(h * scale));
      canvas = document.createElement("canvas");
      canvas.width = tw;
      canvas.height = th;
      ctx = canvas.getContext("2d", { alpha: false });
      if (!ctx) return file;
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, tw, th);
      ctx.drawImage(fuente, 0, 0, tw, th);
      const blob = await canvasABlob(canvas, "image/jpeg", JPEG_CALIDAD);
      const base = String(file.name || "hoja").replace(/\.[^.]+$/, "") || "hoja";
      return new File([blob], `${base}.jpg`, { type: "image/jpeg", lastModified: Date.now() });
    } catch (error) {
      console.log("[AL] Compresión de imagen omitida", error);
      return file;
    } finally {
      if (ctx && canvas) ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (canvas) {
        canvas.width = 0;
        canvas.height = 0;
      }
      if (fuente) {
        if (typeof fuente.close === "function") fuente.close();
        fuente.onload = null;
        fuente.onerror = null;
        if (fuente.src) fuente.src = "";
      }
    }
  }

  function enlazarCargaHoja(id) {
    const input = $(id);
    if (!input) return;
    enlazarDesbloqueoVoz(input.closest("label") || input);
    input.addEventListener("change", (event) => {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (file) subirDocumento(file).catch((err) => responder(err.message));
    });
  }

  async function subirDocumento(file) {
    desbloquearVozIos();
    await pushChat("al", "Comprimiendo y leyendo la hoja de papel…", { evento: "ocr_inicio" });
    const compacta = await comprimirImagenCliente(file);
    const form = new FormData();
    form.append("archivo", compacta, compacta.name || "hoja.jpg");
    const response = await fetch("/api/ocr/upload", { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (response.status === 403 && data.bloqueado) {
      bloquearLicencia(data.licencia || data);
      throw new Error(data.detail);
    }
    if (!response.ok) throw new Error(data.detail || "No se pudo leer la hoja");
    const acumulando = (state.inventario.skus || []).length > 0 || state.modoSumarHoja;
    aplicarInventarioCargado(data.inventario, data.sku_activo || data.skuActivo);
    const hojas = hojasDelContenedor();
    const kpis = state.kpis || {};
    const mensaje = acumulando && hojas > 1
      ? `Hoja ${hojas} sumada al contenedor ${state.inventario.contenedor || "actual"}. Acumulado: ${kpis.skus_totales || 0} SKUs y ${kpis.cajas_esperadas || 0} cajas.`
      : data.mensaje || `Contenedor cargado. Hoja ${hojas || 1}.`;
    await responder(mensaje, { evento: "carga_documento" });
  }

  async function cargarDemo() {
    const data = await api("/api/ocr/demo", { method: "POST" });
    aplicarSesion(data);
    await responder(data.mensaje, { evento: "carga_demo" });
  }

  function enlazarUi() {
    $("mic-fab").addEventListener("click", toggleMic);
    enlazarDesbloqueoVoz($("mic-fab"));
    enlazarDesbloqueoVoz($("btn-estatus"));
    enlazarDesbloqueoVoz($("btn-sumar-hoja"));
    const btnDemo = $("btn-demo");
    if (btnDemo) {
      btnDemo.addEventListener("click", () => cargarDemo().catch((err) => responder(err.message)));
    }
    enlazarCargaHoja("file-input-camera");
    enlazarCargaHoja("file-input-gallery");
    const fileInputLegacy = $("file-input");
    if (fileInputLegacy) enlazarCargaHoja("file-input");
    $("tabla-filtro").addEventListener("input", (event) => {
      state.filtro = event.target.value;
      renderTabla();
    });
    $("sku-modal-close").addEventListener("click", () => $("sku-modal").classList.add("hidden"));
    $("complete-alert-close").addEventListener("click", () => mostrarCompleto(false));
    const btnWhatsappCierre = $("complete-alert-whatsapp");
    if (btnWhatsappCierre) {
      btnWhatsappCierre.addEventListener("click", () => {
        const registro =
          state.ultimoCierre || construirRegistroCierre() || leerHistorialContenedores().slice(-1)[0];
        copiarTextoWhatsApp(textoWhatsAppCierre(registro));
      });
    }
    $("btn-sumar-cajas").addEventListener("click", () => conteoManual("sumar"));
    $("btn-fijar-cajas").addEventListener("click", () => conteoManual("editar"));
    $("btn-estatus").addEventListener("click", () => {
      desbloquearVozIos();
      reportarEstatus().catch((err) => responder(err.message));
    });
    const modalEstatus = document.getElementById("modal-estatus");
    if (modalEstatus) {
      modalEstatus.addEventListener("click", (event) => {
        if (event.target === modalEstatus) cerrarModalEstatus();
      });
    }
    const btnSumarHoja = $("btn-sumar-hoja");
    if (btnSumarHoja) btnSumarHoja.addEventListener("click", () => prepararSiguienteHoja());
    const btnCerrarContenedor = $("btn-cerrar-contenedor");
    if (btnCerrarContenedor) {
      btnCerrarContenedor.addEventListener("click", () => cerrarContenedorManual().catch((err) => responder(err.message)));
    }
    const btnHistorial = $("btn-historial");
    if (btnHistorial) btnHistorial.addEventListener("click", abrirHistorial);
    const historialClose = $("historial-close");
    if (historialClose) historialClose.addEventListener("click", cerrarHistorial);
    const historialResumen = $("historial-resumen-dia");
    if (historialResumen) historialResumen.addEventListener("click", () => copiarResumenDia());
    const historialFecha = $("historial-fecha");
    if (historialFecha) {
      historialFecha.addEventListener("change", (event) => {
        state.historialFecha = event.target.value;
        renderHistorial();
      });
    }
    const historialLimpiar = $("historial-limpiar");
    if (historialLimpiar) historialLimpiar.addEventListener("click", limpiarHistorialCierres);
    $("paleta-input").addEventListener("change", (event) => guardarPaleta(event.target.value));
    $("btn-limpiar-chat").addEventListener("click", () => limpiarChat());
    const btnSettings = $("btn-settings");
    if (btnSettings) btnSettings.addEventListener("click", abrirAjustesComandos);
    const settingsClose = $("settings-close");
    if (settingsClose) settingsClose.addEventListener("click", cerrarAjustesComandos);
    const settingsSave = $("settings-save");
    if (settingsSave) settingsSave.addEventListener("click", guardarComandosVoz);
  }

  async function iniciar() {
    pintarIdentidadCliente(licenciaClienteValida());
    if (!licenciaClienteValida()) {
      bloquearLicencia({
        detail:
          "Licencia Expirada o Inválida. Por favor contacte al desarrollador para renovar su servicio.",
      });
      if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("/static/sw.js").catch(() => {});
      }
      return;
    }

    state.config = { ...CONFIG_LOCAL };
    aplicarComandosPersonalizados();
    enlazarUi();
    const local = leerInventarioLocal();
    const sesionLocal = Boolean(local && local.inventario);
    const tieneLocal = Boolean(sesionLocal && (local.inventario.skus || []).length);
    if (sesionLocal) {
      aplicarInventarioCargado(local.inventario, local.skuActivo, { restaurar: true });
    }

    try {
      const licencia = await api("/api/license/status");
      if (licencia.bloqueada) {
        bloquearLicencia(licencia);
        return;
      }
      pintarIdentidadCliente(true);
      state.config = await api("/api/config");
      aplicarComandosPersonalizados();
    } catch {
      pintarIdentidadCliente(true);
      aplicarComandosPersonalizados();
    }

    $("wake-hint").textContent = `Di “${(state.config.wake_word || "oye al").replace(/\b\w/g, (c) => c.toUpperCase())}”`;

    if (!sesionLocal) {
      try {
        const sesion = await api("/api/inventario");
        if (sesion.inventario && (sesion.inventario.skus || []).length) {
          aplicarSesion(sesion);
        }
      } catch {
        /* modo 100% local: no hay backend */
      }
    }

    try {
      const chat = await api("/api/chat");
      state.chat = chat.mensajes || [];
      renderChat();
    } catch {
      state.chat = [];
      renderChat();
    }

    if (!state.chat.length) {
      const mensaje = tieneLocal
        ? "Inventario recuperado del teléfono. Di Oye AL para continuar o cargue otro archivo."
        : "AL listo. Escanee o cargue la foto de la hoja, o di Oye AL.";
      await pushChat("al", mensaje, { evento: tieneLocal ? "boot_local" : "boot" });
    }

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/static/sw.js").catch(() => {});
    }
  }

  window.cerrarModalEstatus = cerrarModalEstatus;

  iniciar();
})();

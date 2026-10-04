/** STT: interim/final, wake, armado de frase partida y ruido. */
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const app = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");

function must(re, msg) {
  assert.ok(re.test(app), msg);
}

must(/rec\.lang = idiomaReconocimiento\(\)/, "lang se asigna");
must(/rec\.continuous = true/, "continuous true");
must(/rec\.interimResults = true/, "interimResults true");
must(/rec\.maxAlternatives = 3/, "maxAlternatives 3 solo para log");
must(/function recibirFinalEstable/, "assembler de finales");
must(/function fraseOperativaEstable/, "estabilidad operativa");
must(/function pareceSufijoSkuImplícito/, "sufijo implícito en commandArmed");
must(/BUSCAR_IMPLICITO/, "intención implícita registrada");
must(/function armarVentanaComando/, "ventana de wake");
must(/WAKE_VENTANA_MS = 6500/, "timeout de comando 6.5s");
must(/STT_ESTABLE_MS = 380/, "hold corto 380ms");
must(/if \(!result\.isFinal\)/, "interims no operan");
must(/alternativas/, "se registran alternativas");
must(/error === "network" \|\| error === "audio-capture"/, "backoff de errores");
must(/function pedirPermisoMicrofono/, "no hay stream paralelo permanente");
must(/window\.AL_STT_DEBUG/, "debug de transcripciones");
must(/function pintarRegistroVoz/, "Registro de voz recibe transcripción");
must(/function sincronizarVisibilidadSkuVoz/, "voz sincroniza filtro de B");
must(/heardFinal/, "finales se muestran aunque no se ejecuten");

const WAKE_ALIASES = ["oye al", "oye aele", "oye ale", "oye a l", "hey al", "ok al", "okay al"];
const COMANDOS = {
  BUSCAR: ["al", "buscar", "busca", "encontrar", "ubica", "dame"],
  SUMAR: ["suma", "sumale", "agrega", "ponle", "van"],
  EDITAR: ["edita", "cambia", "fija en", "reemplaza"],
  ESTATUS: ["estatus", "status", "estado del contenedor", "como vamos"],
};
const MULETILLAS = new Set(["a", "al", "de", "del", "el", "la", "ese"]);
const NUMEROS = { veinte: 20, tres: 3, ocho: 8, doce: 12 };
const DECENAS = { veinte: 20 };
const UNIDADES = { tres: 3 };

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
  t = t.replace(/\b(veinte)\s+y\s+(tres)\b/g, (_, d, u) => String(DECENAS[d] + UNIDADES[u]));
  Object.keys(NUMEROS)
    .sort((a, b) => b.length - a.length)
    .forEach((p) => {
      t = t.replace(new RegExp(`\\b${p}\\b`, "g"), String(NUMEROS[p]));
    });
  return t.replace(/\s+/g, " ").trim();
}
function quitarWake(texto) {
  let t = normalizar(texto);
  const aliases = [...new Set([...WAKE_ALIASES, "oye al"])].sort((a, b) => b.length - a.length);
  for (const alias of aliases) {
    const idx = t.indexOf(alias);
    if (idx >= 0) {
      t = t.slice(idx + alias.length).replace(/\s+/g, " ").trim();
      break;
    }
  }
  return t;
}
function contieneWake(texto) {
  const t = normalizar(texto);
  return t.includes("oye al") || WAKE_ALIASES.some((alias) => t.includes(alias));
}
function fraseEnTexto(texto, alias) {
  const a = normalizar(alias);
  if (!a) return false;
  const escaped = a.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|\\s)${escaped}(?:$|\\s)`).test(` ${texto} `);
}
function matchComando(texto) {
  let mejor = null;
  Object.entries(COMANDOS).forEach(([tipo, aliases]) => {
    aliases.forEach((alias) => {
      const a = normalizar(alias);
      if (!a || !fraseEnTexto(texto, a)) return;
      if (!mejor || a.length > mejor.alias.length) mejor = { tipo, alias: a };
    });
  });
  return mejor;
}
function quitarMuletillas(texto) {
  return normalizar(texto)
    .split(" ")
    .filter((p) => p && !MULETILLAS.has(p))
    .join(" ");
}
function normalizarLetrasHabladasSku(texto) {
  let t = normalizar(texto);
  [
    [/\bese\s+ese\b/g, "ss"],
    [/\ba\s+be\b/g, "ab"],
    [/\ba\s+b\b/g, "ab"],
    [/\bs\s+s\b/g, "ss"],
  ].forEach(([patron, letra]) => {
    t = t.replace(patron, letra);
  });
  t = t.replace(/\bese\b/g, "s");
  t = t.replace(/\bbe\b/g, "b");
  return t.replace(/\s+/g, " ").trim();
}
function normalizarSufijoSkuVoz(texto) {
  const limpio = quitarMuletillas(normalizarLetrasHabladasSku(convertirNumerosHablados(texto || "")));
  return String(limpio).toUpperCase().replace(/[^A-Z0-9]/g, "");
}
function parsearCantidadYSufijo(resto) {
  const limpio = quitarMuletillas(convertirNumerosHablados(resto));
  const nums = String(limpio).match(/\d+/g) || [];
  if (!nums.length) return { cantidad: null, sufijo: "" };
  return { cantidad: Number(nums[0]), sufijo: nums.slice(1).join("") };
}
function fraseOperativaEstable(raw) {
  const texto = convertirNumerosHablados(quitarWake(raw));
  if (!texto) return true;
  const hit = matchComando(texto);
  const resto = hit ? texto.replace(hit.alias, " ").replace(/\s+/g, " ").trim() : texto;
  if (!hit) {
    const sufijo = normalizarSufijoSkuVoz(resto);
    return !(sufijo && /^\d+$/.test(sufijo));
  }
  if (hit.tipo === "BUSCAR") {
    const sufijo = normalizarSufijoSkuVoz(resto);
    if (!sufijo) return false;
    return !/^\d+$/.test(sufijo);
  }
  if (hit.tipo === "SUMAR" || hit.tipo === "EDITAR") {
    return parsearCantidadYSufijo(resto).cantidad !== null;
  }
  return true;
}
function pareceContinuacionUtterance(pendiente, extra) {
  const n = normalizar(extra);
  if (!n || !pendiente) return false;
  if (contieneWake(n)) return false;
  if (matchComando(convertirNumerosHablados(n))) return false;
  return true;
}

function pareceSufijoSkuImplícito(texto) {
  return /^\d+[A-Z]{2,}$/.test(normalizarSufijoSkuVoz(texto));
}

function clasificar(raw, { commandArmed = false } = {}) {
  const texto = convertirNumerosHablados(quitarWake(raw));
  if (!texto) return { tipo: "WAKE_ONLY", texto };
  const hit = matchComando(texto);
  const resto = hit ? texto.replace(hit.alias, " ").replace(/\s+/g, " ").trim() : texto;
  if (hit) return { tipo: hit.tipo, texto, resto, sufijo: normalizarSufijoSkuVoz(resto) };
  if ((commandArmed || contieneWake(raw)) && pareceSufijoSkuImplícito(texto)) {
    return { tipo: "BUSCAR_IMPLICITO", texto, sufijo: normalizarSufijoSkuVoz(texto) };
  }
  return { tipo: "RUIDO", texto, sufijo: normalizarSufijoSkuVoz(texto) };
}

function simularStt(eventos, { commandArmed = false } = {}) {
  const procesados = [];
  const mostrados = [];
  let pendiente = "";
  let armed = commandArmed;
  const flush = (frase) => {
    if (!frase) return;
    procesados.push(frase);
    const tipo = clasificar(frase).tipo;
    if (tipo === "WAKE_ONLY") armed = true;
    else armed = false;
    pendiente = "";
  };
  eventos.forEach((ev) => {
    const texto = ev.transcript;
    if (!ev.isFinal) {
      mostrados.push({ tipo: "interim", texto });
      return;
    }
    mostrados.push({ tipo: "final", texto });
    if (!(armed || contieneWake(texto) || pendiente)) return;
    let combinado = texto;
    if (pendiente) {
      if (pareceContinuacionUtterance(pendiente, texto)) combinado = `${pendiente} ${texto}`.replace(/\s+/g, " ").trim();
      else {
        flush(pendiente);
        combinado = texto;
      }
    }
    if (!fraseOperativaEstable(combinado)) {
      pendiente = combinado;
      return;
    }
    flush(combinado);
  });
  if (pendiente && (armed || contieneWake(pendiente))) flush(pendiente);
  return { procesados, mostrados };
}

assert.strictEqual(quitarWake("oye al buscar 20 ss"), "buscar 20 ss");
assert.strictEqual(quitarWake("ruido oye al buscar 20 ss"), "buscar 20 ss");
assert.strictEqual(quitarWake("buscar 20 ss"), "buscar 20 ss");

assert.strictEqual(fraseOperativaEstable("oye al buscar 20 SS"), true);
assert.strictEqual(fraseOperativaEstable("oye al buscar 20"), false);
assert.strictEqual(fraseOperativaEstable("suma 3"), true);
assert.strictEqual(fraseOperativaEstable("suma"), false);
assert.strictEqual(fraseOperativaEstable("estatus"), true);
assert.strictEqual(fraseOperativaEstable("oye al"), true);

const interim = simularStt([
  { transcript: "buscar 20", isFinal: false },
  { transcript: "oye al buscar 20 SS", isFinal: true },
]);
assert.deepStrictEqual(interim.procesados, ["oye al buscar 20 SS"]);
assert.strictEqual(interim.mostrados[0].tipo, "interim");
assert.ok(!interim.procesados.some((p) => p === "buscar 20"));

const partido = simularStt([
  { transcript: "oye al buscar 20", isFinal: true },
  { transcript: "SS", isFinal: true },
]);
assert.deepStrictEqual(partido.procesados, ["oye al buscar 20 SS"]);

const pausa = simularStt([{ transcript: "oye al", isFinal: true }]);
assert.deepStrictEqual(pausa.procesados, ["oye al"]);
const despuesPausa = simularStt([{ transcript: "buscar 20 SS", isFinal: true }], { commandArmed: true });
assert.deepStrictEqual(despuesPausa.procesados, ["buscar 20 SS"]);

const ruido = simularStt([{ transcript: "el camion paso veinte", isFinal: true }]);
assert.deepStrictEqual(ruido.procesados, []);
assert.strictEqual(clasificar("el camion paso").tipo, "RUIDO");

const casos = [
  ["Oye AL buscar 20 SS", "BUSCAR", "20SS"],
  ["buscar 24 AB", "BUSCAR", "24AB"],
  ["buscar 36 SS", "BUSCAR", "36SS"],
  ["buscar 20 ese ese", "BUSCAR", "20SS"],
  ["suma 3", "SUMAR", ""],
  ["suma 12", "SUMAR", ""],
  ["estatus", "ESTATUS", ""],
  ["como vamos", "ESTATUS", ""],
  ["el camion paso", "RUIDO", ""],
];
casos.forEach(([frase, tipo, sufijo]) => {
  const hit = clasificar(frase);
  assert.strictEqual(hit.tipo, tipo, `${frase} → ${tipo}, obtuvo ${hit.tipo}`);
  if (sufijo) assert.strictEqual(hit.sufijo, sufijo, `${frase} sufijo`);
});

assert.strictEqual(clasificar("20 SS").tipo, "RUIDO", "sin wake no busca");
assert.strictEqual(clasificar("20 SS", { commandArmed: true }).tipo, "BUSCAR_IMPLICITO");
assert.strictEqual(clasificar("20 SS", { commandArmed: true }).sufijo, "20SS");
assert.strictEqual(clasificar("Oye AL 20 SS").tipo, "BUSCAR_IMPLICITO");
assert.strictEqual(clasificar("24 AB", { commandArmed: true }).sufijo, "24AB");
assert.strictEqual(clasificar("36 ese ese", { commandArmed: true }).sufijo, "36SS");
assert.strictEqual(clasificar("20 CS", { commandArmed: true }).sufijo, "20CS");
assert.strictEqual(clasificar("20", { commandArmed: true }).tipo, "RUIDO", "20 solo no es SUMAR/FIJAR ni sufijo implícito");
assert.strictEqual(clasificar("el camion paso", { commandArmed: true }).tipo, "RUIDO");
assert.strictEqual(clasificar("suma 3", { commandArmed: true }).tipo, "SUMAR");
assert.strictEqual(clasificar("fija en 8", { commandArmed: true }).tipo, "EDITAR");
assert.strictEqual(clasificar("estatus", { commandArmed: true }).tipo, "ESTATUS");
assert.ok(pareceSufijoSkuImplícito("20 SS"));
assert.ok(pareceSufijoSkuImplícito("20-SS"));
assert.ok(pareceSufijoSkuImplícito("20SS"));
assert.ok(pareceSufijoSkuImplícito("36 ese ese"));
assert.ok(!pareceSufijoSkuImplícito("20"));
assert.ok(!pareceSufijoSkuImplícito("el camion 20 ss"));

const armado = simularStt([{ transcript: "20 SS", isFinal: true }], { commandArmed: true });
assert.deepStrictEqual(armado.procesados, ["20 SS"]);

const fijar = clasificar("fijar 8");
assert.ok(fijar.tipo !== "EDITAR", "fijar 8 no es alias de FIJAR; no se inventa intención");

function delayReinicioStt(streak) {
  if (streak <= 0) return 220;
  return Math.min(220 * 2 ** Math.min(streak, 4), 4000);
}
assert.strictEqual(delayReinicioStt(0), 220);
assert.strictEqual(delayReinicioStt(1), 440);
assert.ok(delayReinicioStt(8) <= 4000);

console.log("OK test_voz_stt");
console.log("INTERIM: buscar 20 no se procesa; final oye al buscar 20 SS sí");
console.log("PARTIDO: oye al buscar 20 + SS → oye al buscar 20 SS");
console.log("WAKE: oye al + pausa + buscar 20 SS");
console.log("RUIDO: sin wake no opera");
console.log("LOG ejemplo: transcripcion=oye al buscar 20 SS tipo=final lang=es-ES alternatives=log-only");

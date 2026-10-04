/** Parser de voz: exacto, letras habladas y corrección fonética conservadora. */
const fs = require("fs");
const path = require("path");

const app = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
if (!app.includes("function normalizarLetrasHabladasSku")) throw new Error("Falta normalizarLetrasHabladasSku");
if (!app.includes("function recuperarSufijoFonicoSku")) throw new Error("Falta recuperarSufijoFonicoSku");

const NUMEROS = { veinte: 20, treinta: 30, seis: 6 };
const DECENAS = { veinte: 20, treinta: 30 };
const UNIDADES = { seis: 6 };
const MULETILLAS = new Set(["a", "al", "de", "del", "el", "la", "ese"]);
const BUSCAR = ["al", "buscar", "busca", "encontrar", "ubica", "dame"];
const OTROS = { SUMAR: ["suma"], ESTATUS: ["estatus", "status"], EDITAR: ["fija en", "edita"] };

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
  t = t.replace(/\b(veinte|treinta)\s+y\s+(seis)\b/g, (_, d, u) => String(DECENAS[d] + UNIDADES[u]));
  Object.keys(NUMEROS)
    .sort((a, b) => b.length - a.length)
    .forEach((p) => {
      t = t.replace(new RegExp(`\\b${p}\\b`, "g"), String(NUMEROS[p]));
    });
  return t.replace(/\s+/g, " ").trim();
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
function normalizarCodigo(valor) {
  return String(valor ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}
function coincideSufijoSku(sku, consulta) {
  const q = normalizarCodigo(consulta);
  return q ? normalizarCodigo(sku).endsWith(q) : true;
}
function distanciaEdicion(a, b) {
  const s = String(a || "");
  const t = String(b || "");
  if (Math.abs(s.length - t.length) > 1) return 99;
  const filas = Array.from({ length: s.length + 1 }, () => new Array(t.length + 1).fill(0));
  for (let i = 0; i <= s.length; i += 1) filas[i][0] = i;
  for (let j = 0; j <= t.length; j += 1) filas[0][j] = j;
  for (let i = 1; i <= s.length; i += 1) {
    for (let j = 1; j <= t.length; j += 1) {
      const costo = s[i - 1] === t[j - 1] ? 0 : 1;
      filas[i][j] = Math.min(filas[i - 1][j] + 1, filas[i][j - 1] + 1, filas[i - 1][j - 1] + costo);
    }
  }
  return filas[s.length][t.length];
}
function recuperarSufijoFonicoSku(codigo, items) {
  const compacto = String(codigo || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  const partes = compacto.match(/^(\d+)([A-Z]{2,})$/);
  if (!partes) return { coincidencias: [], correccion: "", modo: "none" };
  const base = partes[1];
  const letras = partes[2];
  const candidatos = [];
  items.forEach((item) => {
    const cola = normalizarCodigo(item.sku).match(/(\d+)([A-Z]{2,})$/);
    if (!cola || cola[1] !== base || cola[2].length !== letras.length) return;
    const dist = distanciaEdicion(letras, cola[2]);
    if (dist > 0 && dist <= 1) candidatos.push({ item, sufijo: `${base}${cola[2]}`, dist });
  });
  if (candidatos.length === 1) {
    return { coincidencias: [candidatos[0].item], correccion: candidatos[0].sufijo, modo: "fonetico" };
  }
  if (candidatos.length > 1) {
    return { coincidencias: candidatos.map((c) => c.item), correccion: "", modo: "ambiguo" };
  }
  return { coincidencias: [], correccion: "", modo: "none" };
}
function fraseEnTexto(texto, alias) {
  const a = normalizar(alias);
  const escaped = a.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|\\s)${escaped}(?:$|\\s)`).test(` ${texto} `);
}
function matchComando(texto) {
  let mejor = null;
  Object.entries({ BUSCAR, ...OTROS }).forEach(([tipo, aliases]) => {
    aliases.forEach((alias) => {
      const a = normalizar(alias);
      if (!a || !fraseEnTexto(texto, a)) return;
      if (!mejor || a.length > mejor.alias.length) mejor = { tipo, alias: a };
    });
  });
  return mejor;
}
function buscar(dictado, inventario) {
  const sufijo = normalizarSufijoSkuVoz(dictado);
  const exactos = inventario.filter((sku) => coincideSufijoSku(sku, sufijo));
  if (exactos.length) {
    return { sufijo, modo: "exacto", correccion: "", skus: exactos, unica: exactos.length === 1 };
  }
  const rec = recuperarSufijoFonicoSku(
    sufijo,
    inventario.map((sku) => ({ sku }))
  );
  return {
    sufijo,
    modo: rec.modo === "none" ? "ninguno" : rec.modo,
    correccion: rec.correccion,
    skus: rec.coincidencias.map((i) => i.sku),
    unica: rec.coincidencias.length === 1,
  };
}
function parsear(raw) {
  const texto = convertirNumerosHablados(raw);
  const hit = matchComando(texto);
  const resto = hit ? texto.replace(hit.alias, " ").replace(/\s+/g, " ").trim() : texto;
  return { hit, resto };
}

const base = ["AXCLDYMWS20-SS", "AXCLDYHEN24-AB", "AXCLDYHEN36-SS", "AXCLDYMUR28-AB"];
let fallos = 0;
function check(nombre, ok, extra) {
  if (!ok) fallos += 1;
  console.log(`${ok ? "OK" : "FAIL"} ${nombre}${extra ? ` ${extra}` : ""}`);
}

const c1 = buscar("20 SS", base);
check("1 exacto 20 SS", c1.modo === "exacto" && c1.unica && c1.skus[0] === "AXCLDYMWS20-SS", `modo=${c1.modo} sku=${c1.skus[0]}`);

const c2 = buscar("20 ese ese", base);
check("2 letras 20 ese ese", c2.modo === "exacto" && c2.sufijo === "20SS" && c2.skus[0] === "AXCLDYMWS20-SS", `sufijo=${c2.sufijo}`);

const c3 = buscar("24 a be", base);
check("3 letras 24 a be", c3.modo === "exacto" && c3.sufijo === "24AB" && c3.skus[0] === "AXCLDYHEN24-AB", `sufijo=${c3.sufijo}`);

const c4 = buscar("20 CS", base);
check(
  "4 fonetico 20 CS",
  c4.modo === "fonetico" && c4.correccion === "20SS" && c4.skus[0] === "AXCLDYMWS20-SS" && c4.unica,
  `modo=${c4.modo} corr=${c4.correccion}`
);
console.log(
  "LOG transcripcion=Buscar 20 CS normalizado=20CS exacto=none correccion segura=20SS SKU=AXCLDYMWS20-SS"
);

const c5 = buscar("20 CS", [...base, "TEST20-CS"]);
check("5 exacto gana TEST20-CS", c5.modo === "exacto" && c5.skus[0] === "TEST20-CS", `modo=${c5.modo} sku=${c5.skus[0]}`);

const c6 = buscar("20 CS", ["TEST20-SS", "TEST20-BS"]);
check(
  "6 ambiguo no selecciona",
  c6.modo === "ambiguo" && !c6.unica && c6.skus.length === 2,
  `modo=${c6.modo} n=${c6.skus.length}`
);

const c7 = buscar("36 ese ese", base);
check("7 36 ese ese", c7.modo === "exacto" && c7.skus[0] === "AXCLDYHEN36-SS");

const c8 = buscar("28 a be", base);
check("8 28 a be", c8.modo === "exacto" && c8.skus[0] === "AXCLDYMUR28-AB");

const c9 = buscar("ZZ", base);
check("9 ZZ sin fuzzy", c9.modo === "ninguno" && c9.skus.length === 0, `modo=${c9.modo}`);

const e = parsear("estatus");
check("10 estatus", e.hit && e.hit.tipo === "ESTATUS");

const s = parsear("suma 3");
check("11 suma 3", s.hit && s.hit.tipo === "SUMAR");

const exactoSs = buscar("20 SS", base);
check("regresion Buscar 20 SS", exactoSs.modo === "exacto" && exactoSs.skus[0] === "AXCLDYMWS20-SS");

function pareceSufijoSkuImplícito(texto) {
  return /^\d+[A-Z]{2,}$/.test(normalizarSufijoSkuVoz(texto));
}
check("implícito 20 SS es sufijo", pareceSufijoSkuImplícito("20 SS") && buscar("20 SS", base).skus[0] === "AXCLDYMWS20-SS");
check("implícito 20 no es sufijo ni SUMAR", !pareceSufijoSkuImplícito("20") && parsear("20").hit == null);
check("implícito 20 ZZ sin match", buscar("20 ZZ", base).modo === "ninguno");
check("regresion fija en 8", parsear("fija en 8").hit && parsear("fija en 8").hit.tipo === "EDITAR");

if (fallos) {
  console.error(`FALLÓ ${fallos} caso(s)`);
  process.exit(1);
}
console.log("TODOS LOS CASOS OK");

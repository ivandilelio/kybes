// Fase 2: paginazione a cursore, query dichiarate, Unit of Work (TypeORM su sql.js).
import "reflect-metadata";
import assert from "node:assert/strict";
import { DataSource } from "typeorm";
import { ENTITIES, ModelValidationError, runInTransaction, isolationFor } from "./model/generated";
import type { PageRequest } from "./model/generated";
import { ClientiRepository } from "./model/Clienti";
import { Ordini, OrdiniRepository } from "./model/Ordini";
import { ProdottiRepository } from "./model/Prodotti";

const SQLITE = { levels: { read_committed: null, repeatable_read: null, serializable: null } };

async function invalid(p: Promise<unknown>, field: string) {
  await assert.rejects(p, (e: unknown) => e instanceof ModelValidationError && field in e.fields);
}

async function all(fetch: (page: PageRequest) => Promise<{ items: Ordini[]; nextCursor: string | null }>, limit: number, sort?: string) {
  const out: Ordini[] = [];
  let cursor: string | null = null;
  let pages = 0;
  for (;;) {
    const pg = await fetch({ limit, cursor, sort });
    out.push(...pg.items);
    pages++;
    if (!pg.nextCursor) return { out, pages };
    cursor = pg.nextCursor;
  }
}

async function main() {
  const ds = new DataSource({ type: "sqljs", entities: ENTITIES, synchronize: true, logging: false });
  await ds.initialize();
  await ds.query("PRAGMA foreign_keys = ON");
  const em = ds.manager;
  const cr = new ClientiRepository(em), orr = new OrdiniRepository(em), pr = new ProdottiRepository(em);
  const a = await cr.create({ ragioneSociale: "Alfa" });
  const b = await cr.create({ ragioneSociale: "Beta", attivo: false });
  await cr.create({ ragioneSociale: "Gamma" });
  for (let i = 0; i < 25; i++) {
    await orr.create({ numero: `2026/${String(i).padStart(3, "0")}`, clienteId: i % 2 === 0 ? a.id : b.id,
      data: `2026-01-0${1 + (i % 5)}`, totale: String(i), stato: i % 3 ? "aperto" : "chiuso" });
  }
  // pagine complete, niente duplicati, ordine data desc + id
  const { out, pages } = await all((p) => orr.listPage(p), 7);
  assert.equal(pages, 4);
  assert.equal(new Set(out.map((o) => o.id)).size, 25);
  const keys = out.map((o) => [o.data, o.id] as const);
  const sorted = [...keys].sort((x, y) => (x[0] === y[0] ? (x[1] < y[1] ? -1 : 1) : x[0] < y[0] ? 1 : -1));
  assert.deepEqual(keys, sorted);
  const byNum = await all((p) => orr.listPage(p), 10, "numero");
  assert.deepEqual(byNum.out.map((o) => o.numero), [...byNum.out.map((o) => o.numero)].sort());
  const tot = (await orr.listPage({ limit: 200, sort: "-totale" })).items.map((o) => Number(o.totale));
  assert.deepEqual(tot, [...tot].sort((x, y) => y - x));
  // contratto
  await invalid(orr.listPage({ sort: "note" }), "sort");
  await invalid(orr.listPage({ limit: 0 }), "limit");
  await invalid(orr.listPage({ limit: 201 }), "limit");
  await invalid(orr.listPage({ cursor: "xxx" }), "cursor");
  const c1 = (await orr.listPage({ limit: 5 })).nextCursor;
  await invalid(orr.listPage({ limit: 5, sort: "numero", cursor: c1 }), "cursor");
  assert.equal((await orr.listPage()).limit, 50);
  // query dichiarate
  const dal = (await orr.listDelClienteDal(a.id, "2026-01-04", { limit: 100 })).items;
  assert.ok(dal.length > 0 && dal.every((o) => o.clienteId === a.id && o.data >= "2026-01-04"));
  await invalid(orr.listDelClienteDal(a.id, "2026-01-01", { sort: "numero" }), "sort");
  const aperti = (await orr.listApertiDelCliente(a.id, { limit: 100 })).items;
  assert.ok(aperti.length > 0 && aperti.every((o) => o.stato === "aperto" && o.clienteId === a.id));
  const ultimo = await orr.findUltimoDelCliente(a.id);
  assert.equal(ultimo?.data, out.filter((o) => o.clienteId === a.id).map((o) => o.data).sort().pop());
  await orr.create({ numero: "X%_1", clienteId: a.id, data: "2026-02-01" });
  await orr.create({ numero: "XA_1", clienteId: a.id, data: "2026-02-01" });
  assert.deepEqual((await orr.listPerNumero("X%", { limit: 10 })).items.map((o) => o.numero), ["X%_1"]);
  assert.deepEqual((await orr.listPerNumero("2026/00", { limit: 100 })).items.map((o) => o.numero),
    Array.from({ length: 10 }, (_, i) => `2026/00${i}`));
  assert.deepEqual((await cr.listAttivi()).items.map((c) => c.ragioneSociale), ["Alfa", "Gamma"]);
  await pr.create({ codice: "A", descrizione: "a" });
  await pr.create({ codice: "B", descrizione: "b" });
  assert.deepEqual(new Set((await pr.listSenzaCategoria()).map((p) => p.codice)), new Set(["A", "B"]));
  assert.deepEqual((await pr.listPerCodici(["B", "Z"])).map((p) => p.codice), ["B"]);
  assert.deepEqual(await pr.listPerCodici([]), []);
  const figli = await cr.listOrdini(a.id, { limit: 3 });
  assert.ok(figli.items.length === 3 && figli.nextCursor !== null && figli.items.every((o) => o.clienteId === a.id));
  // Unit of Work
  assert.equal(isolationFor(["Clienti"]), "read_committed");
  assert.equal(isolationFor(["Ordini", "RigheOrdine"]), "serializable");
  const id = await runInTransaction(ds, async (tx) => (await new ClientiRepository(tx).create({ ragioneSociale: "Delta" })).id, SQLITE);
  assert.ok(await cr.getById(id));
  await assert.rejects(runInTransaction(ds, async (tx) => {
    await new ClientiRepository(tx).create({ ragioneSociale: "Epsilon" });
    throw new Error("errore applicativo");
  }, SQLITE), /errore applicativo/);
  assert.ok(!(await cr.listPage({ limit: 100 })).items.some((c) => c.ragioneSociale === "Epsilon"), "rollback");
  let n = 0;
  const res = await runInTransaction(ds, async (tx) => {
    n++;
    await new ClientiRepository(tx).create({ ragioneSociale: `Zeta${n}` });
    if (n < 3) throw Object.assign(new Error("serialization failure"), { code: "40001" });
    return n;
  }, { ...SQLITE, tables: ["RigheOrdine"], backoffMs: 0 });
  assert.equal(res, 3);
  const names = new Set((await cr.listPage({ limit: 100 })).items.map((c) => c.ragioneSociale));
  assert.ok(names.has("Zeta3") && !names.has("Zeta1") && !names.has("Zeta2"), "solo il tentativo riuscito resta");
  console.log("TYPESCRIPT ACCESS OK: paginazione keyset, ordinamenti, errori del contratto, query, Unit of Work");
}
main().catch((e) => { console.error(e); process.exit(1); });

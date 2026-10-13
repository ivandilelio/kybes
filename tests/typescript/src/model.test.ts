import "reflect-metadata";
import assert from "node:assert/strict";
import { DataSource } from "typeorm";
import { ENTITIES, ModelValidationError, bindTenant } from "./model/generated";
import { ClientiRepository } from "./model/Clienti";
import { OrdiniRepository } from "./model/Ordini";
import { RigheOrdineRepository } from "./model/RigheOrdine";
import { ProdottiRepository } from "./model/Prodotti";
import { CategorieRepository } from "./model/Categorie";

const TENANT = "00000000-0000-4000-8000-0000000000aa";

async function main() {
  const ds = new DataSource({ type: "sqljs", entities: ENTITIES, synchronize: true, logging: false });
  await ds.initialize();
  await ds.query("PRAGMA foreign_keys = ON");
  const em = ds.manager;
  bindTenant(em, TENANT);
  const cr = new ClientiRepository(em), orr = new OrdiniRepository(em), rr = new RigheOrdineRepository(em);
  const pr = new ProdottiRepository(em), kr = new CategorieRepository(em);
  const c = await cr.create({ ragioneSociale: "ACME Srl", partitaIva: "01234567890" });
  assert.ok(c.id && c.attivo === true && c.creatoIl instanceof Date);
  assert.equal((await cr.findByPartitaIva("01234567890"))?.id, c.id);
  await assert.rejects(cr.create({ ragioneSociale: "Doppio", partitaIva: "01234567890" }), /UNIQUE/);
  await assert.rejects(cr.create({ ragioneSociale: "x".repeat(201) }), (e: unknown) =>
    e instanceof ModelValidationError && e.fields["RagioneSociale"] === "lunghezza massima 200");
  await assert.rejects(cr.update(c.id, { id: "x" } as never), ModelValidationError);
  const root = await kr.create({ nome: "Root" });
  const sub = await kr.create({ nome: "Sub", padreId: root.id });
  assert.deepEqual((await kr.listFiglie(root.id)).items.map((x) => x.nome), ["Sub"]);
  assert.equal((await kr.getPadre(sub.id))?.nome, "Root");
  const p = await pr.create({ codice: "P1", descrizione: "Bullone", categoriaId: sub.id, attributi: { colore: "rosso" } });
  const o = await orr.create({ numero: "2026/1", clienteId: c.id, data: "2026-10-13" });
  const r = await rr.create({ ordineId: o.id, prodottoId: p.id, quantita: 3, prezzoUnitario: "1.5" });
  assert.equal((await orr.getCliente(o.id))?.ragioneSociale, "ACME Srl");
  assert.deepEqual((await cr.listOrdini(c.id)).items.map((x) => x.numero), ["2026/1"]);
  assert.deepEqual((await orr.listByClienteId(c.id)).items.map((x) => x.id), [o.id]);
  assert.deepEqual((await orr.listRighe(o.id)).items.map((x) => x.quantita), [3]);
  assert.equal((await rr.getProdotto(r.id))?.codice, "P1");
  assert.equal((await pr.getCategoria(p.id))?.nome, "Sub");
  assert.equal(await cr.count(), 1);
  assert.ok(await cr.exists(c.id));
  assert.equal((await cr.update(c.id, { email: "info@acme.it" }))?.email, "info@acme.it");
  assert.equal(await orr.delete(o.id), true);
  assert.equal(await rr.count(), 0, "cascade su righe");
  assert.equal(await cr.delete(c.id), true);
  assert.equal(await cr.delete(c.id), false);
  console.log("TYPESCRIPT OK: CRUD, relazioni, auto-relazione, cascade, validazione, default");
}
main().catch((e) => { console.error(e); process.exit(1); });

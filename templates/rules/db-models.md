---
paths:
  - "libs/db-models/**"
  - "schemas/**"
  - "MODEL_INDEX.md"
---

# Regole per modello dati e schemi

- `schemas/db/<Tabella>.yaml` è l'unica sorgente di verità. Tabella o colonna nuova: modifica lo schema e basta. Il generatore riparte da solo e aggiorna tutti i linguaggi, `schemas/json/` e `MODEL_INDEX.md`.
- `model/generated/`, `schemas/json/` e `MODEL_INDEX.md` non si modificano mai a mano.
- Ogni tabella ha un solo file custom: `model/<Tabella>.cs|.py|.ts` oppure `model/<Tabella>Repository.java`. Lì vanno solo i metodi custom di quella tabella, con nomi diversi da quelli generati (CRUD, `findBy*`, `listBy*`, `get<Relazione>`, `list<Relazione>`).
- Prima di aggiungere un metodo leggi `MODEL_INDEX.md`: se esiste già tra i generati, usalo.
- Niente altri file o sottocartelle nella cartella model.
- Le transazioni le apre e chiude il service chiamante.
- Bump di versione semver della libreria DB-Models: patch per fix, minor per tabelle o colonne aggiunte, major per colonne rimosse o rinominate.
- Le migrazioni si eseguono solo dalla pipeline.

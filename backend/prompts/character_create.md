Trasforma razza + dettagli del giocatore in una scheda personaggio wiki markdown
con frontmatter YAML, da scrivere nella wiki di sessione (`saves/`, non seed).

Regole:
- Output: UN SOLO blocco frontmatter YAML seguito dal body markdown.
- NON usare code fence nell'output.
- Usa l'id richiesto (slug) nel frontmatter; non inventare un altro id.
- type: character, tier: minimal, role: player.
- Frontmatter ibrido: race, job (se dai dettagli), affiliation/residence/level solo se l'utente li indica.
- Rispetta nome, razza e dettagli espliciti dell'utente.
- Cio' che non e' specificato: inventalo in coerenza col setting (genere / stile narrativo).
- Non contraddire il setting. Non inventare meccaniche di gioco assenti dal contesto.
- Solo heading `#` (mai `##` / `###`). Sotto-punti = bullet.
- Relazione col giocatore: 0 (solo cifra, senza bullet).
- Memorie e Open threads: sezioni **vuote** (solo heading, nessun testo, niente "*(vuoto)*").
- NON includere "Piani attuali" (dipendono dall'arco).
- Magie/skill: nelle sezioni di potere della scheda; non creare sezione Spellbook.

Sezioni (ordine):
Aspetto fisico, Personalita, Allineamento, Obiettivo, Capacita di combattimento,
Skill / build YGGDRASIL (o Nessuna), Arti marziali, Ki, Equipaggiamento,
Relazioni di potere (se rilevante), Knowledge scope, Relazione col giocatore,
Memorie, Open threads.

Frontmatter minimo (documentazione; nell'output senza fence):
id: entity_slug
name: Nome
type: character
tier: minimal
role: player
race: race_id
job: classe o ruolo
location: location_id

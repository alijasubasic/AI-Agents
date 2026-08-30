# prospecting

Finds the businesses in an area across Google Maps, OpenStreetMap and a
directory, merges them into one row per business, and reads each company's own
website for the name, email address and phone number.

```bash
python -m agents.prospecting.demo          # fixtures, no key, no network
python -m agents.supervisor "Dachdecker" "München"   # the real platforms
```

---

## Kurzanleitung (deutsch)

```bash
make demo                                       # alles mit Testdaten
make leads WHAT="Dachdecker" WHERE="München"    # echte Suche, CSV in leads/
```

Ohne API-Key läuft die Suche über OpenStreetMap. Mit `GOOGLE_MAPS_API_KEY` in
der `.env` kommt Google Maps dazu. Die CSV-Datei enthält pro Betrieb: Firma,
Ansprechpartner, Position, E-Mail, **E-Mail-Status**, Telefon, Website, Adresse,
Plattformen und die Quelle jeder Angabe.

Der Status ist die wichtigste Spalte:

| Status | Bedeutung | Darf angeschrieben werden |
|---|---|---|
| `bestätigt` | vom Betrieb selbst veröffentlicht (Impressum, Kontaktseite) | ja |
| `gemeldet` | steht in einem Verzeichnis oder Kartendienst | nur nach Prüfung durch einen Menschen |
| `geraten` | aus dem Namensmuster gebaut, nirgends veröffentlicht | nein |
| `ungültig` | No-Reply-Postfach oder syntaktisch kaputt | nein |

---

## The one idea worth taking from this agent

**A contact detail is worth exactly as much as the place it was published.**

Two email addresses look identical as strings:

```
m.reiter@reiter-bedachungen.example    printed in the company's own imprint
s.sailer@sailer-dach.example           built from "Stefan Sailer" + the domain
```

The first is a fact. The second is a guess that happens to be formatted like a
fact, and sending to it means writing to whoever actually owns that mailbox —
possibly nobody, possibly a stranger. Every product that promises "verified
emails from Google Maps" is selling a mixture of the two without saying which is
which.

So the difference is a field, not a footnote:

```python
class ContactStatus(StrEnum):
    CONFIRMED = "confirmed"  # the business published it, on its own domain
    REPORTED = "reported"  # a third party says so
    CONSTRUCTED = "constructed"  # a pattern produced it
    INVALID = "invalid"  # no-reply, or not an address at all
```

`Lead.best_email()` returns only `CONFIRMED` addresses. The outreach policy
refuses anything else. Codex article A9 blocks it again at the supervisor. A
guess is still *shown* — a salesperson may well try it by hand and take
responsibility for that — but no automated step will use it.

## Where each field comes from

| Field | Source | Typical status |
|---|---|---|
| Name, address, categories | Google Places, OpenStreetMap, directory | — |
| Phone | all three platforms, and the imprint | `reported`, `confirmed` from the site |
| **Email** | **only the company's own website** | `confirmed` |
| Contact person and role | the imprint, which is legally obliged to name them | `confirmed` |

**No map platform returns email addresses.** Google's Places API never has, and
no field mask produces one. That is why `HttpPageFetcher` exists, and why
`--no-web` turns a lead list into a phone list:

```
without reading websites   0 of 5 businesses have an email address
with                       3 of 5
```

## The merge

The same roofer is `Alpenblick Dach & Fassade` on Google Maps,
`Alpenblick Dach und Fassade KG` on OpenStreetMap, and again in a directory. One
business, three rows, and a salesperson who calls all three looks careless.

Matching is deterministic, over three keys, any one of which is enough:

```
normalised name + postcode     "alpenblick dach fassade|81669"
phone in E.164                 "+498955504410"
website domain                 "alpenblick-dach.example"
```

Shared keys are unioned transitively, so A↔B on a phone number and B↔C on a
domain puts all three together. Nothing is fuzzy: two similar names at different
addresses stay separate. That asymmetry is deliberate — a missed merge is a
visible duplicate somebody fixes in seconds, while a wrong merge deletes a real
business from the list and nobody ever finds out.

## What the model does, and what it does not

```
the model      writes the search queries
the platforms  decide which businesses exist
the regexes    decide what their contact details are
the statuses   decide which of those may be used
```

That is the entire division of labour. The model never sees a company record and
never produces a contact detail, so it cannot invent one. Ask a model for "the
email address on this page" and it will give you one whether or not the page
contains it — and the invention is indistinguishable from the real thing until
the mail bounces, or worse, until it does not.

Running without a model at all is a supported mode: `default_plan()` produces
"trade + place" queries and the rest of the pipeline is unchanged.

## Lawfulness, briefly

Everything collected here is published by the business itself, and German law
requires most of it to be published. That makes reading it lawful. It does not
make *writing* to it lawful — that question belongs to
[`agents/outreach`](../outreach), which answers it in code.

Two constraints are built in rather than left to the operator's conscience:
`HttpPageFetcher` obeys `robots.txt` and waits between requests, and nothing
anywhere scrapes the Google Maps interface, which would breach its licence. The
Places API is the supported route and the only one implemented.

## Files

| File | What is in it |
|---|---|
| `models.py` | `Listing`, `Lead`, `ContactPoint`, `ContactStatus` |
| `extraction.py` | emails, phones, people — regular expressions, no model |
| `merge.py` | the three-key union, confidence, one row per business |
| `providers.py` | Places / Overpass / page fetcher, mocks and live |
| `agent.py` | the pipeline, the export row, the table |
| `fixtures.py` | five invented roofers, one per interesting path |

## What this does not do

- **Contact forms.** A firm that publishes a form instead of an address stays
  reachable by phone only. Filling forms is not something this should do
  quietly.
- **Trades outside the OSM tag table.** About twenty are mapped; the rest fall
  back to a name search, which finds fewer businesses and never the wrong kind.
- **Pagination.** One page of Places results per query, 20 businesses maximum.
- **Opening hours, ratings over time, photos.** Retrieved where free, unused.

Both gaps above are scored, failing, in
[`evals/cases/prospecting.py`](../../evals/cases/prospecting.py).

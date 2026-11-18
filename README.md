# justitie-mcp

Server MCP care îi dă lui Claude (Claude Code / Claude Desktop) acces la **datele publice ale
instanțelor din România** și la **legislația consolidată**, direct din serviciile oficiale ale
Ministerului Justiției (`portalquery.just.ro` și `legislatie.just.ro`). Nu trece prin niciun
intermediar, nu cere cont și nu cere cheie API.

Proiect neoficial, fără legătură cu Ministerul Justiției.

## Legislație (legislatie.just.ro)

| Unealtă | Ce face |
|---|---|
| `lege_cauta` | Caută acte după titlu, text, număr și an, cu filtru pe tip (LEGE, OUG, HG, ORDIN…). Întoarce id-ul actului, Monitorul Oficial și linkul |
| `lege_cuprins` | Antetul, data ultimei consolidări, istoricul consolidărilor, titlurile și capitolele, plus lista articolelor, opțional filtrată (de ex. „microîntreprinderi”) |
| `lege_articol` | Textul consolidat al unor articole (`291`, `25^1`, `Anexa 1`), cu sau fără notele „(la 01-08-2025, … a fost modificat de …)” |
| `lege_cauta_in_act` | În ce articole dintr-un act apare un text (de ex. „100.000 euro” în Codul fiscal) |

Toate primesc opțional `la_data` (AAAA-LL-ZZ) și atunci folosesc **forma consolidată în vigoare
la acea dată**, aleasă din istoricul de consolidări.

Exemple de întrebări pentru Claude:

- „Ce spune art. 291 din Codul fiscal despre cotele de TVA? Dar la 1 ianuarie 2025?”
- „Care sunt condițiile de microîntreprindere acum?”
- „Unde apare plafonul de 100.000 euro în Codul fiscal?”
- „Arată-mi art. 9 din Legea contabilității 82/1991.”

De știut:

- Căutarea portalului **nu ordonează după relevanță**, iar filtrul de an nu e strict. Serverul
  aplică filtrul de an și tipul local, dar verifică titlul actului.
- Unele acte sunt doar „învelișul” altuia: Legea 227/2015 aprobă Codul fiscal, care are textul
  în alt document. Atunci primești `vezi_textul_in` cu id-ul bun.
- Paginile mari se salvează local pentru 24 de ore, în `%LOCALAPPDATA%\justitie-mcp\legislatie`.
  Pagina Codului fiscal are ~7,5 MB și se descarcă o singură dată; Claude primește doar
  articolele cerute.

## Instanțe (portal.just.ro)

| Unealtă | Ce face |
|---|---|
| `portal_litigii_firma` | Raport de litigii pentru o firmă sau persoană: câte dosare, cu ce calitate (reclamant, pârât, creditor, debitor…), pe categorii și instanțe, **insolvență ca debitor**, termene viitoare. Opțional îl salvează în CSV |
| `portal_cauta_dosare` | Caută după nume parte, număr dosar sau obiect, pe toate instanțele sau pe una, cu filtre de dată (inclusiv „modificat de la”) |
| `portal_dosar` | Fișa completă a unui dosar: părți, toate ședințele cu soluția pe scurt, căi de atac (pentru fiecare instanță prin care a trecut) |
| `portal_sedinte` | Ședințele unei instanțe într-o zi: complete, ore, dosarele de pe rol |
| `portal_institutii` | Lista celor 246 de instanțe și codurile lor |

Totul e **doar citire**.

Exemple de întrebări pentru Claude:

- „Verifică dacă ALFA CONSTRUCT SRL are litigii sau e în insolvență.”
- „Ce termene are clientul X luna asta?”
- „Ce s-a schimbat în dosarele firmei Y de la 1 noiembrie?”
- „Dă-mi fișa dosarului 1234/30/2025.”
- „Fă-mi un CSV cu litigiile clientului Z pentru notele la situațiile financiare.”

## De știut

- **Identificarea se face după denumire**, pentru că portalul nu are CUI. Căutarea găsește
  orice parte al cărei nume *conține* textul căutat. Raportul îți arată `variante_nume`, iar
  apoi restrângi cu `doar_nume` sau `exclude_nume`.
- **Diacriticele nu contează.** Portalul memorează ş/ţ cu sedilă, iar o căutare cu ș/ț cu
  virgulă nu găsește nimic. Serverul scoate singur diacriticele.
- **Limita portalului e de 1000 de dosare pe căutare.** Peste ea rezultatul e trunchiat, iar
  serverul te avertizează. Restrânge atunci căutarea pe instanță, perioadă sau nume.
- **Nu include dosarele ICCJ**, care au un portal separat.
- Datele sunt informative. Pentru acte oficiale contează dosarul de la instanță.
- Răspunsurile stau în cache 10 minute, ca să nu încărcăm portalul.

## Instalare (Windows)

Ai nevoie de [uv](https://docs.astral.sh/uv/). Într-un terminal PowerShell rulezi:

```powershell
uv tool install git+https://github.com/mirceabatranu/justitie-mcp
```

```powershell
justitie-mcp test
```

```powershell
claude mcp add --scope user justitie -- "$env:USERPROFILE\.local\bin\justitie-mcp.exe"
```

Pentru Claude Desktop, adaugi în `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "justitie": { "command": "C:\\Users\\<utilizator>\\.local\\bin\\justitie-mcp.exe" }
  }
}
```

Actualizare: `uv tool upgrade justitie-mcp`.

## Linie de comandă

```powershell
justitie-mcp litigii "ALFA CONSTRUCT" --csv "$env:USERPROFILE\Documents\litigii-alfa.csv"
```

```powershell
justitie-mcp dosar 1234/30/2025
```

## Setări opționale (variabile de mediu)

| Variabilă | Implicit | |
|---|---|---|
| `JUSTITIE_TIMEOUT` | `120` | secunde de așteptare după portal |
| `JUSTITIE_CACHE_SECUNDE` | `600` | cât păstrează răspunsurile în cache |
| `JUSTITIE_PORTAL_URL` | `http://portalquery.just.ro/query.asmx` | adresa serviciului |
| `JUSTITIE_LEGISLATIE_CACHE_ORE` | `24` | cât păstrează paginile de legislație pe disc |
| `JUSTITIE_CACHE_DIR` | `%LOCALAPPDATA%\justitie-mcp` | unde se salvează cache-ul |

## Ce urmează

- Faza 3: registre de pe data.gov.ro (experți judiciari, traducători, practicieni în insolvență)

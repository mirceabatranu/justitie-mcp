# justitie-mcp

Server MCP care îi dă lui Claude (Claude Code / Claude Desktop) acces la **datele publice ale
instanțelor din România**, direct din serviciul oficial al Portalului Instanțelor
(`portalquery.just.ro`). Nu trece prin niciun intermediar, nu cere cont și nu cere cheie API.

Proiect neoficial, fără legătură cu Ministerul Justiției.

## Ce poate face (faza 1: portal.just.ro)

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

## Ce urmează

- Faza 2: legislație (`legislatie.just.ro`, serviciul SOAP oficial `FreeWebService`)
- Faza 3: registre de pe data.gov.ro (experți judiciari, traducători, practicieni în insolvență)

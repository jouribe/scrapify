# scrapyfy

Pipeline de scraping multi-red con Apify y persistencia en PostgreSQL.

## Alcance actual

- Posts:
  - Facebook: `apify/facebook-posts-scraper`
  - Instagram: `apify/instagram-post-scraper`
  - TikTok: `clockworks/tiktok-scraper`
  - LinkedIn: `curious_coder/linkedin-post-search-scraper`
- Comentarios:
  - Facebook: `apify/facebook-comments-scraper`
  - Instagram: `apify/instagram-comment-scraper`
  - TikTok: `clockworks/tiktok-comments-scraper`
- LinkedIn comments queda en espera.

## Requisitos

- Python 3.13+
- UV
- PostgreSQL local (`scrapify`)

## Configuración

1. Copia variables de entorno:

```powershell
Copy-Item .env.example .env
```

2. Actualiza `.env`:

- `DATABASE_URL=postgresql+psycopg://postgres:secret@db:5432/scrapify`
- `POSTGRES_PORT=5434` (puerto en tu máquina host para evitar conflictos)
- `APIFY_API_TOKEN=<tu_token>`
- `LINKEDIN_COOKIE_JSON=<json_de_cookies>` (opcional si no ejecutarás LinkedIn)
- `LOG_LEVEL=INFO` (DEBUG, INFO, WARNING, ERROR)
- `LOG_FILE=scrapyfy.log`

3. Ajusta handles por empresa en `config/targets.yaml`.

## Instalación

```powershell
uv sync
```

## Docker

Puedes correr todo el proyecto (app + PostgreSQL) con Docker Compose.

Este es el flujo recomendado si quieres ejecutar el proyecto 100% dentro de contenedores.

1. Verifica variables:

```powershell
Copy-Item .env.example .env
```

`APIFY_API_TOKEN` debe estar definido en `.env`.

2. Construye imagen y levanta base de datos:

```powershell
docker compose up -d db --build
```

3. Inicializa tablas:

```powershell
docker compose run --rm scrapyfy init-db
```

4. Ejecuta comandos del pipeline:

```powershell
docker compose run --rm scrapyfy run-posts --platforms facebook,instagram,tiktok,linkedin
docker compose run --rm scrapyfy run-comments --platforms facebook,instagram,tiktok
docker compose run --rm scrapyfy run-all
```

5. Apaga servicios:

```powershell
docker compose down
```

Notas:

- El contenedor usa `db` como host de PostgreSQL.
- `DATABASE_URL` en `.env` debe apuntar a `db` para modo solo Docker.
- Puedes cambiar `POSTGRES_PORT` para correr varios proyectos en paralelo (ejemplo: 5434, 5435, 5436).
- Directorios `config`, `inputs`, `external`, `exports` y `logs` se montan como volúmenes para persistir cambios y resultados.

## Comandos

Inicializa tablas:

```powershell
uv run scrapyfy init-db
```

Corre solo posts:

```powershell
uv run scrapyfy run-posts --platforms facebook,instagram,tiktok,linkedin
```

Corre solo comentarios (usa URLs de posts ya guardados):

```powershell
uv run scrapyfy run-comments --platforms facebook,instagram,tiktok
```

Corre pipeline completo:

```powershell
uv run scrapyfy run-all
```

Importa posts desde un dataset existente de Apify para cualquier red (sin relanzar actor):

```powershell
uv run scrapyfy import-posts-dataset <DATASET_ID> --platform facebook
uv run scrapyfy import-posts-dataset <DATASET_ID> --platform instagram
uv run scrapyfy import-posts-dataset <DATASET_ID> --platform tiktok
uv run scrapyfy import-posts-dataset <DATASET_ID> --platform linkedin
uv run scrapyfy import-posts-dataset <DATASET_ID> --platform youtube
```

Importa posts desde un archivo JSON local (por ejemplo, export propio fuera de Apify):

```powershell
uv run scrapyfy import-local-posts <FILE_PATH> --platform tiktok --company-slug yape
```

Ejemplos reales:

```powershell
uv run scrapyfy import-posts-dataset aMG0inCgfZJ8iEEas --platform facebook
uv run scrapyfy import-posts-dataset pGE2tYHtGf0VQGe6U --platform instagram
uv run scrapyfy import-local-posts external/videos_output.json --platform tiktok --company-slug yape
```

Compatibilidad (LinkedIn legacy):

```powershell
uv run scrapyfy import-linkedin-dataset <DATASET_ID>
```

Importa comentarios desde un dataset existente de Apify por plataforma y empresa:

```powershell
uv run scrapyfy import-comments-dataset <DATASET_ID> --platform tiktok --company-slug caja-arequipa
```

Ejemplo real (TikTok):

```powershell
uv run scrapyfy import-comments-dataset E0q09aK1TKGkjX01p --platform tiktok --company-slug caja-arequipa
uv run scrapyfy import-comments-dataset ha3T6wN1EcUfW49dz --platform tiktok --company-slug caja-huancayo
uv run scrapyfy import-comments-dataset cCFaXe6gEterjQrpV --platform tiktok --company-slug entel-peru
```

Corre análisis de sentimiento sobre comentarios persistidos:

```powershell
uv run scrapyfy run-sentiment --platforms facebook,instagram,tiktok,linkedin,youtube
uv run scrapyfy run-sentiment --platforms facebook,instagram,tiktok,linkedin,youtube --company-slug <COMPANY_SLUG>
```

Exporta reporte Excel por empresa (resumen + hojas por red):

```powershell
uv run scrapyfy export-excel caja-arequipa --output-dir ./exports
```

Exporta benchmark Excel por red social para varias marcas (hojas `Resumen`, `Posts` y una por empresa):

```powershell
uv run scrapyfy export-excel --platform facebook --company-slug interbank,mibanco --output-dir ./exports
uv run scrapyfy export-excel --platform facebook --company-slug [company-uno,company-dos] --output-dir ./exports
```

Notas de uso:

- `COMPANY_SLUG` posicional sigue siendo el modo clásico (un solo reporte por empresa).
- `--platform` + `--company-slug` activa el modo benchmark multi-marca.
- `--company-slug` acepta lista separada por comas, con o sin corchetes.
- El archivo generado sigue este patrón:

```powershell
exports/facebook_multi_company_report_YYYY-MM-DD.xlsx
```

## Notas operativas

- La estrategia de persistencia es incremental por `platform + external_id` (upsert).
- Se guardan `raw` y métricas para trazabilidad.
- Los templates en `inputs/` quedaron sin secretos ni URLs hardcodeadas.
- El sistema genera logs en consola y en `logs/scrapyfy.log` con rotación automática.
- LinkedIn: los comentarios anidados de cada post se persisten automáticamente durante `run-posts`.

## Calidad de sesión LinkedIn

LinkedIn requiere cookies válidas y activas para paginar más allá de la primera página (10 posts).
Cuando la sesión está degradada el actor devuelve los mismos 10 posts repetidos, y el pipeline
emite una advertencia en consola y en el log:

```
WARNING  LinkedIn session quality is poor: unique_ratio=5% (10 unique / 200 raw). ...
```

Cuando esto ocurre el pipeline **reduce automáticamente** el límite (`limitPerSource`) a 20 para las
empresas restantes, ahorrando créditos de Apify.

### Cómo refrescar las cookies de LinkedIn

1. Instala la extensión **Cookie Editor** en Chrome o Firefox.
2. Abre [linkedin.com](https://www.linkedin.com) y asegúrate de estar logueado.
3. Haz clic en Cookie Editor → **Export** → **Export as JSON**.
4. Compacta el JSON a una sola línea (puedes usar `jq -c . cookies.json`).
5. Actualiza `LINKEDIN_COOKIE_JSON` en `.env` con ese valor.
6. Verifica que el token `li_at` esté presente en el JSON exportado.

```powershell
# Validación rápida: contar cookies
uv run python -c "
import os, json; from dotenv import load_dotenv; load_dotenv()
cookies = json.loads(os.getenv('LINKEDIN_COOKIE_JSON','[]'))
names = [c.get('name') for c in cookies]
print(f'Cookies: {len(cookies)}')
print('li_at present:', any(n == 'li_at' for n in names))
"
```

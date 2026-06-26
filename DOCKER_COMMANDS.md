# scrapyfy: guia de comandos usando solo Docker

Esta guia muestra como usar todo el proyecto sin instalar Python/uv en tu maquina host.

## 1) Preparacion inicial

1. Crear archivo de entorno:

```powershell
Copy-Item .env.example .env
```

2. Verificar variables minimas en `.env`:

- `APIFY_API_TOKEN=<tu_token>`
- `DATABASE_URL=postgresql+psycopg://postgres:secret@db:5432/scrapify`
- `POSTGRES_PORT=5434` (puerto en host; puedes cambiarlo si esta ocupado)
- `LINKEDIN_COOKIE_JSON=<json_de_cookies>` (opcional)

**Opcional - DigitalOcean Spaces (para subidas automáticas de Excel):**

- `DIGITALOCEAN_SPACES_KEY=<tu_access_key>`
- `DIGITALOCEAN_SPACES_SECRET=<tu_secret_key>`
- `DIGITALOCEAN_SPACES_NAME=<nombre_del_space>`
- `DIGITALOCEAN_SPACES_REGION=nyc3` (región, default: nyc3)
- `DIGITALOCEAN_SPACES_ENDPOINT=` (opcional, se auto-configura)

3. Levantar solo la base de datos (recomendado):

```powershell
docker compose up -d db --build
```

4. Inicializar tablas:

```powershell
docker compose run --rm scrapyfy init-db
```

## 2) Flujo diario (pipeline)

Ejecutar posts:

```powershell
docker compose run --rm scrapyfy run-posts --platforms facebook,instagram,tiktok,linkedin
```

Ejecutar comentarios:

```powershell
docker compose run --rm scrapyfy run-comments --platforms facebook,instagram,tiktok
```

Nota: este comando scrapea comentarios para posts ya persistidos en la base.

Ejecutar todo (posts + comentarios):

```powershell
docker compose run --rm scrapyfy run-all
```

## 3) Importaciones de datasets/archivos

Importar posts desde dataset de Apify:

```powershell
docker compose run --rm scrapyfy import-posts-dataset <DATASET_ID> --platform facebook
docker compose run --rm scrapyfy import-posts-dataset <DATASET_ID> --platform instagram
docker compose run --rm scrapyfy import-posts-dataset <DATASET_ID> --platform tiktok
docker compose run --rm scrapyfy import-posts-dataset <DATASET_ID> --platform linkedin
docker compose run --rm scrapyfy import-posts-dataset <DATASET_ID> --platform youtube
```

Importar posts desde JSON local:

```powershell
docker compose run --rm scrapyfy import-local-posts external/videos_output.json --platform tiktok --company-slug yape
```

Importar comentarios de posts desde dataset de Apify (sin volver a correr actor):

```powershell
docker compose run --rm scrapyfy import-comments-dataset <DATASET_ID> --platform tiktok --company-slug caja-arequipa
```

Tambien puedes usar facebook, instagram o youtube en `--platform`.

Compatibilidad LinkedIn legacy:

```powershell
docker compose run --rm scrapyfy import-linkedin-dataset <DATASET_ID>
```

## 4) Sentimiento y reportes

Analisis de sentimiento (todas las plataformas disponibles):

```powershell
docker compose run --rm scrapyfy run-sentiment --platforms facebook,instagram,tiktok,linkedin,youtube
```

Analisis de sentimiento para una empresa:

```powershell
docker compose run --rm scrapyfy run-sentiment --platforms facebook,instagram,tiktok,linkedin,youtube --company-slug caja-arequipa
```

Export Excel de una empresa:

```powershell
docker compose run --rm scrapyfy export-excel caja-arequipa --output-dir ./exports
```

Export Excel benchmark multiempresa por plataforma:

```powershell
docker compose run --rm scrapyfy export-excel --platform facebook --company-slug interbank,mibanco --output-dir ./exports
```

**Descargar desde URL (si DigitalOcean Spaces está configurado):**

Si configuraste `DIGITALOCEAN_SPACES_*` en `.env`, el archivo se cargará automáticamente a Spaces y verás:

```
✓ Report saved: ./exports/report.xlsx
✓ Uploaded to Spaces: https://mi-space.nyc3.digitaloceanspaces.com/exports/report.xlsx
```

Para desactivar la carga a Spaces en un comando específico:

```powershell
docker compose run --rm scrapyfy export-excel caja-arequipa --output-dir ./exports --upload-to-spaces false
```

## 5) Listado de comentarios

Mostrar todos los links de comentarios agrupados por plataforma y compañía:

```powershell
docker compose run --rm scrapyfy list-comment-links
```

Filtrar por plataforma:

```powershell
docker compose run --rm scrapyfy list-comment-links --platform facebook
docker compose run --rm scrapyfy list-comment-links --platform instagram
docker compose run --rm scrapyfy list-comment-links --platform tiktok
```

Filtrar por compañía:

```powershell
docker compose run --rm scrapyfy list-comment-links --company-slug interbank
docker compose run --rm scrapyfy list-comment-links --company-slug caja-arequipa
```

Combinar filtros (plataforma + compañía):

```powershell
docker compose run --rm scrapyfy list-comment-links --platform instagram --company-slug interbank
docker compose run --rm scrapyfy list-comment-links --platform facebook --company-slug caja-arequipa
```

Nota: Los links se muestran agrupados por plataforma y compañía, con cada link en una línea separada.

## 5.1) Listado de posts

Mostrar todos los links de posts agrupados por plataforma y compañía:

```powershell
docker compose run --rm scrapyfy list-post-links
```

Filtrar por plataforma:

```powershell
docker compose run --rm scrapyfy list-post-links --platform facebook
docker compose run --rm scrapyfy list-post-links --platform instagram
docker compose run --rm scrapyfy list-post-links --platform tiktok
docker compose run --rm scrapyfy list-post-links --platform linkedin
```

Filtrar por compañía:

```powershell
docker compose run --rm scrapyfy list-post-links --company-slug interbank
docker compose run --rm scrapyfy list-post-links --company-slug scotiabank-peru
```

Combinar filtros (plataforma + compañía):

```powershell
docker compose run --rm scrapyfy list-post-links --platform instagram --company-slug scotiabank-peru
docker compose run --rm scrapyfy list-post-links --platform facebook --company-slug interbank
```

Nota: Los links se muestran agrupados por plataforma y compañía, con cada link en una línea separada.

## 5.2) Listado de compañías

Mostrar todas las compañías registradas con sus slugs:

```powershell
docker compose run --rm scrapyfy list-companies
```

Nota: Esta información es útil para usar en los filtros `--company-slug` de otros comandos.

## 5.3) Agregar una nueva compañía

Agregar una compañía interactivamente (el slug se genera automáticamente):

```powershell
docker compose run --rm scrapyfy add-company
```

Se te pedirá:

- **Nombre**: El nombre completo de la compañía (ej: "BBVA Perú")
- **Slug**: Se generará automáticamente (ej: "bbva-peru"). Puedes confirmarlo o ingresar uno personalizado
- **Redes Sociales** (opcional): URLs de Facebook, Instagram, TikTok, LinkedIn y YouTube

Ejemplo de ejecución:

```
? Company name: BBVA Perú
? Use slug 'bbva-peru'?: [Y/n]
? Enter social media handles (press Enter to skip):
  Facebook: https://www.facebook.com/bbvaenperu
  Instagram: https://www.instagram.com/bbva_peru
  TikTok:
  LinkedIn:
  YouTube:

✓ Company registered successfully!

Summary:
──────────────────────────────────────────────
Name:  BBVA Perú
Slug:  bbva-peru
Handles:
  • Facebook: https://www.facebook.com/bbvaenperu
  • Instagram: https://www.instagram.com/bbva_peru
──────────────────────────────────────────────
```

Nota: Los cambios se guardan en `config/targets.yaml` (montado como volumen en Docker)

**Local (con .env.local):**

```powershell
.\.venv\Scripts\python -m scrapyfy.cli add-company
```

## 6) Comandos utiles de Docker

Ver logs de la base:

```powershell
docker compose logs -f db
```

Ver estado de servicios:

```powershell
docker compose ps
```

Apagar servicios:

```powershell
docker compose down
```

Apagar y eliminar volumen de datos (reset total):

```powershell
docker compose down -v
```

## 8) Notas importantes

- El contenedor usa `db` como host de PostgreSQL.
- Los directorios `config`, `inputs`, `external`, `exports` y `logs` se montan como volumenes.
- Los archivos exportados se guardan en `exports/` del proyecto.
- Si cambias dependencias o codigo base de imagen, vuelve a construir:

```powershell
docker compose build scrapyfy
```

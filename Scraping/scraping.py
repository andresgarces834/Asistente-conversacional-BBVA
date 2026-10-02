"""Scraper de bbva.com.co para alimentar un asistente conversacional (RAG).

Flujo:
    1. Lee el sitemap.xml y filtra las URLs permitidas por robots.txt.
    2. Visita cada URL con un navegador real (el sitio bloquea clientes HTTP simples).
    3. Extrae el contenido principal en texto limpio, conservando los titulos.
    4. Guarda una pagina por linea en data/paginas.jsonl (se puede reanudar).

Uso:
    python scraping.py --limit 10   # solo las primeras 10 paginas (pruebas)
    python scraping.py              # todo el sitio
    python scraping.py --seccion personas/productos <- donde se puede filtrar por cualquier texto de la URL

Nota: el WAF de BBVA bloquea Chrome headless, por eso se abre con ventana.
"""

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.bbva.com.co"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
OUTPUT = Path(__file__).parent / "data" / "paginas.jsonl"
PAUSA_SEGUNDOS = 1.0  # No sobrecargar el servidor con consultas instantaneas (evitar bloqueos)

# robots.txt: Disallow: *.content.html  y  /personas/cards
EXCLUIDAS = (".content.html", "/personas/cards")

# Elementos que no aportan informacion
RUIDO = "script, style, noscript, svg, header, footer, nav, form, iframe, [class*=cookie], [id*=cookie]"

########################################################################################
####################    OBTENCION URLS Y LIMPIEZA DE TEXTO    ##########################
########################################################################################

def url_permitida(url: str) -> bool:
    return not any(p in url for p in EXCLUIDAS)

def obtener_urls(page, context, filtro: str | None) -> list[dict]:
    """Devuelve [{'url', 'lastmod'}] desde el sitemap."""
    page.goto(BASE_URL, wait_until="domcontentloaded")  # el WAF exige sesion previa
    xml = context.request.get(SITEMAP_URL).text()
    items = re.findall(r"<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", xml)
    urls = [{"url": u, "lastmod": m or None} for u, m in items if url_permitida(u)]
    if filtro:
        urls = [u for u in urls if filtro in u["url"]]
    return urls

def limpiar_texto(texto: str) -> str:
    texto = re.sub(r"[ \t\xa0]+", " ", texto)
    texto = re.sub(r"^- *\n+\s*", "- ", texto, flags=re.M)  # viñeta pegada a su texto
    texto = re.sub(r"\n\s*\n+", "\n\n", texto)
    return texto.strip()

########################################################################################
##########################    EXTRACCION DE CONTENIDO    ###############################
########################################################################################

def extraer_contenido(html: str) -> dict:
    """Convierte el HTML en titulo, descripcion, headings y texto limpio."""
    soup = BeautifulSoup(html, "lxml")

    titulo = soup.title.get_text(strip=True) if soup.title else ""
    meta = soup.find("meta", attrs={"name": "description"})
    descripcion = meta.get("content", "").strip() if meta else ""

    main = soup.find("main") or soup.body or soup
    for tag in main.select(RUIDO):
        tag.decompose()

    # Titulos como markdown (#, ##, ...) para poder hacer chunking por secciones
    for h in main.find_all(re.compile(r"^h[1-6]$")):
        nivel = int(h.name[1])
        h.replace_with(f"\n\n{'#' * nivel} {h.get_text(' ', strip=True)}\n\n")
    for li in main.find_all("li"):
        li.insert_before("\n- ")

    texto = limpiar_texto(main.get_text(separator="\n"))
    headings = re.findall(r"^#{1,6} (.+)$", texto, flags=re.M)

    return {"titulo": titulo, "descripcion": descripcion, "headings": headings, "texto": texto}

########################################################################################
####################    EVITAR DUPLICACION POR RE-EJECUCION   ##########################
########################################################################################

def cargar_ya_procesadas() -> set[str]:
    if not OUTPUT.exists():
        return set()
    with OUTPUT.open(encoding="utf-8") as f:
        return {json.loads(linea)["url"] for linea in f if linea.strip()}

########################################################################################
#####################    EXTRACCION Y CREACION DE METADATOS   ##########################
########################################################################################

def clasificar(url: str) -> dict:
    """Seccion y categoria de la URL, para poder filtrar en el RAG."""
    partes = [p for p in url.replace(BASE_URL, "").split("/") if p]
    partes = [p.removesuffix(".html") for p in partes]
    return {
        "seccion": partes[0] if partes else "home",
        "categoria": partes[1] if len(partes) > 1 else "",
        "subcategoria": partes[2] if len(partes) > 2 else "",
    }

##########################################################
#####################    MAIN   ##########################
##########################################################

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="maximo de paginas a procesar")
    ap.add_argument("--seccion", help="solo URLs que contengan este texto")
    ap.add_argument("--headless", action="store_true", help="sin ventana (el sitio suele bloquearlo)")
    args = ap.parse_args()

    OUTPUT.parent.mkdir(exist_ok=True)
    hechas = cargar_ya_procesadas()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=args.headless)
        context = browser.new_context(locale="es-CO")
        page = context.new_page()

        urls = [u for u in obtener_urls(page, context, args.seccion) if u["url"] not in hechas]
        if args.limit:
            urls = urls[: args.limit]
        print(f"{len(urls)} URLs por procesar ({len(hechas)} ya guardadas)")

        errores = []
        with OUTPUT.open("a", encoding="utf-8") as out:
            for i, item in enumerate(urls, 1):
                url = item["url"]
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    try:  # el sitio hace peticiones constantes; si no se calma, seguimos igual
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        page.wait_for_timeout(2000)
                    if resp is None or resp.status >= 400:
                        raise RuntimeError(f"HTTP {resp.status if resp else '?'}")
                    registro = {
                        "url": url,
                        "lastmod": item["lastmod"],
                        **clasificar(url),
                        **extraer_contenido(page.content()),
                        "scraped_at": datetime.now(timezone.utc).isoformat(),
                    }
                    out.write(json.dumps(registro, ensure_ascii=False) + "\n")
                    out.flush()
                    print(f"[{i}/{len(urls)}] OK  {url} ({len(registro['texto'])} chars)")
                except Exception as e:  # una pagina rota no debe detener el resto
                    errores.append({"url": url, "error": str(e)[:200]})
                    print(f"[{i}/{len(urls)}] ERR {url}: {str(e)[:80]}")
                time.sleep(PAUSA_SEGUNDOS)

        browser.close()

    if errores:
        (OUTPUT.parent / "errores.json").write_text(
            json.dumps(errores, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{len(errores)} errores -> data/errores.json")

if __name__ == "__main__":
    main()

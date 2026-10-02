# PRESENTACION PRUEBA TECNICA - SECCION SCRAPING

### Objetivo:
BBVA Colombia necesita un asistente conversacional que permita a usuarios internos consultar
informacion publicada en su sitio web institucional (https://www.bbva.com.co/), sin depender de
busquedas manuales.

### Pasos para realizar el scraping - ETL:

#### Extracción:

1. Inicialmente se consulta el archivo de texto plano "robots.txt" del sitio web con el objetivo
de encontrar la ubicacion exacta del archivo "sitemap.xml", se identifican las rutas que el sitio 
no permite rastrear (*.content.html y /personas/cards), que se excluyen.

2. Una vez ubicado el archivo "sitemap.xml", tenemos conocimiento de como movernos por la 
pagina web y cada una de las URL con toda la informacion, en este caso se encontraron 1240 URL,
de las cuales se filtran las no permitidas.

3. Con las fuentes listas, se desarrolla el codigo que recorre cada URL del sitemap, este proceso
depende netamente de la cantidad de informacion en cada una las URLs. En esta etapa se detectó que 
el sitio bloquea clientes automatizados (respuesta 403 con curl, requests y Chrome sin ventana). 
Por eso se usa Playwright con Chrome con ventana, que el sitio acepta. Se aplica una pausa de 1 
segundo entre páginas para no sobrecargar el servidor y evitar el posible bloqueo.

4. Al ser 1240 URLs aproximadamente, se toma la opcion de almacenar todo en un archivo .jsonl
para no tener un archivo por URL (.json) y dejar todo centralizado y evitar re-escritura si algo
falla.

5. Se elimina el ruido (menús, footer, scripts, formularios), se normalizan espacios y saltos de 
línea y se conserva la estructura de títulos. Esto reduce fallas en la normalización posterior.

6. Se extrae el contenido de las paginas de la siguiente manera: "titulo", "descripcion", 
"headings" y "texto", esta decision se toma teniendo en cuenta el chatbot, ya que son las
caracteristicas basicas para que el entienda de qué trata cada contenido y pueda dividirlo en 
fragmentos coherentes.

7. Adicionalmente en este punto se extraen los metadatos completos de cada URL, cada registro 
incluye la URL, la fecha de modificación del sitemap, la fecha de extracción y una clasificación 
(seccion, categoria, subcategoria). Permiten citar la fuente de cada respuesta y filtrar la
búsqueda por tipo de contenido.

8. Finalmente para este primer scraping, se crea un JSON con los errores ocurridos durante
la ejecucion (solo si ocurren), esto debido a que es de vital importancia dado la cantidad de 
URLs existentes y permite reintentar solo las que fallaron.

#### Transformación:


# Cómo contribuir

¡Gracias por querer sumarte! Esta guía explica cómo reportar problemas, proponer
ideas y mandar cambios para que lleguen rápido a una versión publicada.

Al participar aceptás el [código de conducta](CODE_OF_CONDUCT.md).

## Reportar un error

1. Asegurate de tener la última versión: abrí la aplicación con internet y aceptá
   la actualización si te la ofrece. Muchos errores de descarga se deben a cambios
   de YouTube que ya están resueltos en una versión nueva.
2. Buscá en los [issues](https://github.com/aldomrodriguez/tube-downloader/issues)
   si ya alguien lo reportó. Si existe, sumá tu caso ahí en vez de abrir otro.
3. Abrí un [reporte de error](https://github.com/aldomrodriguez/tube-downloader/issues/new?template=reporte-de-error.yml)
   con el link del video (si es público), lo que esperabas, lo que pasó, el mensaje
   de error y tu placa de video.

Los problemas de seguridad **no** van en un issue: seguí la
[política de seguridad](SECURITY.md).

## Proponer una idea

Abrí una [sugerencia](https://github.com/aldomrodriguez/tube-downloader/issues/new?template=sugerencia.yml)
contando qué problema resolvería. La aplicación apuesta a ser simple —pegar link,
descargar, editar—, así que las ideas que suman opciones se evalúan con cuidado.
Para cambios grandes, conviene charlarlo en un issue antes de escribir código.

## Mandar cambios

### Preparar el entorno

Necesitás Windows 10/11 y Python 3.11 o superior.

```powershell
git clone https://github.com/<tu-usuario>/tube-downloader.git
cd tube-downloader
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe app.py
```

Para probar el ejecutable final: `.\build.ps1` (queda en `dist\TubeDownloader.exe`).

### Flujo de trabajo

1. Hacé un fork y creá una rama desde `main` con un nombre descriptivo
   (`arreglo/progreso-playlist`, `mejora/subtitulos`).
2. Hacé cambios chicos y enfocados: un pull request por tema.
3. Probá a mano lo que tocaste. Como mínimo:
   - un video que baje en H.264 sin convertir (1080p o menos),
   - uno en 4K que necesite conversión,
   - detener una descarga a la mitad y cerrar la ventana durante una conversión.
4. Abrí el pull request completando la plantilla: qué cambia, por qué y cómo lo
   probaste. Si toca la interfaz, agregá una captura.

### Estilo de código

- Seguí el estilo del archivo que estés tocando (PEP 8, 4 espacios, líneas de
  hasta ~90 caracteres).
- La interfaz está en castellano rioplatense ("pegá", "elegí"); los comentarios y
  nombres en el código, en inglés.
- Los comentarios explican el **por qué**, no el qué. Si una decisión no es obvia
  (un límite de hardware, un bug de una dependencia), dejala escrita.
- Nunca bloquees el hilo de la interfaz: el trabajo pesado va en un hilo aparte y
  vuelve a la UI con `root.after(...)`.
- No agregues dependencias sin charlarlo antes: cada una engorda el ejecutable.

### Mensajes de commit

En castellano, en presente, con un título corto que diga qué cambia y, si hace
falta, un párrafo explicando por qué:

```
Corrige el progreso en playlists con videos privados

yt-dlp saltea los videos privados sin avisar al hook, así que el
contador quedaba trabado en el anterior.
```

## Publicar versiones (mantenedores)

Está todo en [RELEASING.md](RELEASING.md).

## Licencia

Al contribuir, aceptás que tu aporte se publique bajo la [GPL-3.0](LICENSE), la
misma licencia del proyecto.

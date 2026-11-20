# Cómo publicar una versión

🇦🇷 **Español** · [🇬🇧 English](RELEASING.en.md)

Guía para mantenedores. Cada versión publicada en
[Releases](https://github.com/aldomrodriguez/tube-downloader/releases) les llega a
todos los usuarios por la actualización automática, así que este proceso es lo único
que hace falta para distribuir un cambio.

## Pasos

1. **Hacé los cambios** y probalos (ver la lista en
   [CONTRIBUTING.md](CONTRIBUTING.md#flujo-de-trabajo)).

2. **Subí la versión** en `app.py`:

   ```python
   APP_VERSION = "1.0.1"
   ```

   Es el único lugar donde está la versión: `build.ps1` la copia a los metadatos
   del `.exe` y el actualizador la compara con el tag del release.

3. **Anotá los cambios** en [`CHANGELOG.md`](CHANGELOG.md) **y en
   [`CHANGELOG.en.md`](CHANGELOG.en.md)**, arriba de todo, con la fecha y el enlace al
   final del archivo:

   ```markdown
   ## [1.0.1] — 2026-12-05

   - Corrige la descarga de Shorts.

   [1.0.1]: https://github.com/aldomrodriguez/tube-downloader/releases/tag/v1.0.1
   ```

4. **Compilá:**

   ```powershell
   .\build.ps1
   ```

   Instala el yt-dlp más nuevo, empaqueta y firma `dist\TubeDownloader.exe`. Abrilo
   y probá una descarga antes de seguir.

5. **Commit y push:**

   ```powershell
   git add -A
   git commit -m "Versión 1.0.1"
   git push
   ```

6. **Publicá el release** con [GitHub CLI](https://cli.github.com/):

   Escribí las notas en un archivo (por ejemplo `notas.md`, guardado en UTF-8) y
   pasalo con `--notes-file`. Escribirlas directo en el comando con `--notes` puede
   romper los acentos según la consola, y así se verían en el aviso de la app.

   ```powershell
   gh release create v1.0.1 dist\TubeDownloader.exe `
     --title "Tube Downloader 1.0.1" `
     --notes-file notas.md
   ```

   O desde la web: **Releases → Draft a new release**, tag `v1.0.1`, y adjuntar
   `dist\TubeDownloader.exe`.

## Reglas que no se pueden romper

El actualizador depende de estas tres cosas; si alguna falla, los usuarios no ven
la actualización:

- El tag es `v` + la versión de `APP_VERSION` (por ejemplo `v1.0.1`).
- El ejecutable adjunto se llama exactamente `TubeDownloader.exe`.
- El release no está marcado como borrador ni como pre-release. Al revés: marcarlo
  así es la forma de subir algo para probar sin que les llegue a los usuarios.

Las notas del release se muestran en el aviso de actualización (las primeras ~280
letras), así que conviene que sean cortas y digan lo que le importa al usuario.

## Qué número usar

Versionado semántico, `MAYOR.MENOR.PARCHE`:

| Cambio | Ejemplo | Nueva versión |
|---|---|---|
| Arreglos, yt-dlp actualizado | Vuelven a andar los Shorts | `1.0.0` → `1.0.1` |
| Funciones nuevas | Descargar solo el audio | `1.0.1` → `1.1.0` |
| Cambios grandes o incompatibles | Rediseño completo | `1.1.0` → `2.0.0` |

## Mantenimiento: recompilar aunque no haya cambios

yt-dlp va dentro del ejecutable. Cuando YouTube cambia algo, las descargas pueden
empezar a fallar, y la única forma de arreglarlo para los usuarios es publicar una
versión nueva compilada con el yt-dlp actualizado.

Por eso conviene publicar una versión de parche:

- apenas alguien reporte errores de descarga que antes no pasaban, y
- cada tanto (por ejemplo, una vez por mes) aunque nadie haya reportado nada.

En ese caso alcanza con los pasos 2 a 6, con una nota como
"- yt-dlp actualizado para seguir los cambios de YouTube."

## Si algo sale mal

- **Publicaste un exe roto:** publicá enseguida una versión más nueva con el arreglo.
  Borrar el release no alcanza, porque quien ya actualizó se queda con el exe roto
  hasta que haya uno más nuevo.
- **Los usuarios no ven la actualización:** revisá las tres reglas de arriba. Podés
  comprobar lo que ve la app con:

  ```powershell
  .\venv\Scripts\python.exe -c "import updater; print(updater.check_latest('0.0.0'))"
  ```

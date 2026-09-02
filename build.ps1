$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path "$root\venv")) {
    Write-Host "Creando entorno virtual..."
    python -m venv venv
}

$venvPython = "$root\venv\Scripts\python.exe"

Write-Host "Instalando dependencias..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

Write-Host "Localizando ffmpeg embebido..."
$ffmpegPath = & $venvPython -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
Write-Host "ffmpeg: $ffmpegPath"

Write-Host "Generando ejecutable con PyInstaller..."
& $venvPython -m PyInstaller --onefile --windowed --name "TubeDownloader" `
  --add-binary "$ffmpegPath;." `
  --add-data "$root\assets\SpaceGrotesk.ttf;." `
  --add-data "$root\assets\SpaceGrotesk-OFL.txt;." `
  --collect-data customtkinter `
  --version-file "$root\version_info.txt" `
  --distpath "$root\dist" --workpath "$root\build" --specpath "$root" app.py

$exe = "$root\dist\TubeDownloader.exe"

# Firma de codigo. Busca el certificado por asunto, asi sobrevive a que lo
# regeneres. Si no hay ninguno la compilacion sigue igual: firmar es opcional.
Write-Host ""
Write-Host "Firmando el ejecutable..."
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -like "*Aldo Rodriguez*" -and $_.NotAfter -gt (Get-Date) } |
        Sort-Object NotAfter -Descending | Select-Object -First 1

if (-not $cert) {
    Write-Host "  No hay certificado de firma; el exe queda sin firmar."
} else {
    # PyInstaller puede dejar el archivo tomado un instante despues de cerrar.
    $free = $false
    foreach ($i in 1..10) {
        try { $fs = [System.IO.File]::Open($exe,'Open','ReadWrite','None'); $fs.Close(); $free = $true; break }
        catch { Start-Sleep -Seconds 2 }
    }
    if (-not $free) {
        Write-Host "  El exe esta en uso (cerra la app); queda sin firmar."
    } else {
        # El sellado de tiempo mantiene valida la firma despues de que el
        # certificado venza. Si no hay internet, se firma igual sin sello.
        try {
            $r = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert `
                 -HashAlgorithm SHA256 -TimestampServer "http://timestamp.digicert.com" -ErrorAction Stop
        } catch {
            $r = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert -HashAlgorithm SHA256
            Write-Host "  Sin sellado de tiempo (no hubo conexion)."
        }
        Write-Host "  Firmado como: $($cert.Subject)"
    }
}

Write-Host ""
Write-Host "Listo. Ejecutable generado en: $exe"

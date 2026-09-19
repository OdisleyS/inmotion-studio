[CmdletBinding()]
param(
    [string]$Destination,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $PSScriptRoot "..\assets\models\piper"
}

$voices = @(
    @{
        Name = "pt_BR-faber-medium"
        Model = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx?download=true"
        Config = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json?download=true"
    },
    @{
        Name = "en_US-amy-medium"
        Model = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx?download=true"
        Config = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json?download=true"
    }
)

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

foreach ($voice in $voices) {
    $files = @(
        @{ Url = $voice.Model; Path = Join-Path $Destination "$($voice.Name).onnx" },
        @{ Url = $voice.Config; Path = Join-Path $Destination "$($voice.Name).onnx.json" }
    )

    foreach ($file in $files) {
        if ((Test-Path -LiteralPath $file.Path) -and -not $Force) {
            Write-Host "ja existe: $($file.Path)"
            continue
        }

        $temporary = "$($file.Path).download"
        try {
            Write-Host "baixando: $($file.Path)"
            Invoke-WebRequest -Uri $file.Url -OutFile $temporary -UseBasicParsing
            if (-not (Test-Path -LiteralPath $temporary) -or (Get-Item -LiteralPath $temporary).Length -lt 1024) {
                throw "download vazio ou incompleto"
            }
            Move-Item -LiteralPath $temporary -Destination $file.Path -Force
        } finally {
            if (Test-Path -LiteralPath $temporary) {
                Remove-Item -LiteralPath $temporary -Force
            }
        }
    }
}

Write-Host "Piper pronto: portugues Faber e ingles Amy em $Destination"

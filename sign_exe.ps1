# sign_exe.ps1 - Authenticode code signing for Brain Lead applications
param(
    [string]$FilePath,
    [string]$ExportCertPath
)

$ErrorActionPreference = 'Stop'

Write-Host "==> Resolving Brain Lead Code Signing Certificate..." -ForegroundColor Yellow

$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue | Where-Object { $_.Subject -like "*Brain Lead*" } | Select-Object -First 1

if (-not $cert) {
    Write-Host "Creating new Brain Lead Code Signing Certificate..." -ForegroundColor Cyan
    $cert = New-SelfSignedCertificate -Type Custom `
        -Subject "CN=Brain Lead Software, O=Brain Lead" `
        -KeySpec Signature `
        -KeyUsage DigitalSignature `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3") `
        -NotAfter (Get-Date).AddYears(10)
}

Write-Host "Using Certificate: $($cert.Subject) [Thumbprint: $($cert.Thumbprint)]" -ForegroundColor Green

if ($FilePath -and (Test-Path $FilePath)) {
    Write-Host "Signing binary: $FilePath" -ForegroundColor Cyan
    try {
        $sig = Set-AuthenticodeSignature -FilePath $FilePath -Certificate $cert -TimestampServer "http://timestamp.digicert.com" -HashAlgorithm SHA256
    } catch {
        $sig = Set-AuthenticodeSignature -FilePath $FilePath -Certificate $cert -HashAlgorithm SHA256
    }
    Write-Host "Signature Status: $($sig.Status) ($($sig.StatusMessage))" -ForegroundColor Green
}

if ($ExportCertPath) {
    $exportDir = Split-Path $ExportCertPath
    if ($exportDir -and -not (Test-Path $exportDir)) {
        New-Item -ItemType Directory -Path $exportDir -Force | Out-Null
    }
    Export-Certificate -Cert $cert -FilePath $ExportCertPath -Force | Out-Null
    Write-Host "Exported Certificate to: $ExportCertPath" -ForegroundColor Green
}

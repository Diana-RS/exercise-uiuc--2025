Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "C:\tmp\test_extractor"

if (-not (Test-Path "output")) {
    New-Item -ItemType Directory -Path "output" | Out-Null
}

$repositories = @(
    "https://github.com/pytest-dev/pytest.git",
    "https://github.com/django/django.git",
    "https://github.com/pallets/flask.git"
)

foreach ($repo in $repositories) {
    $repoName = (Split-Path $repo -Leaf) -replace ".git$", ""
    $outputFile = "output/${repoName}_assertions.csv"
    
    Write-Host "Processing $repoName..."
    
    try {
        python .\main.py $repo $outputFile
        
        if (Test-Path $outputFile) {
            Write-Host "Results saved to $outputFile"
        } else {
            Write-Host "Failed to process $repoName"
        }
    }
    catch {
        Write-Host "Error processing $repoName : $_" -ForegroundColor Red
        if (Test-Path $outputFile) {
            Remove-Item $outputFile
        }
    }
}

Write-Host "All repositories processed."
# train_all_markets.ps1
# Helper script to train feature models and late-day continuation models for all registered markets sequentially.

Write-Output "Starting multi-market training sequence..."

# Execute the feature model script with the --all flag
python -m src.feature_model --all

if ($LASTEXITCODE -eq 0) {
    Write-Output "All markets trained successfully."
} else {
    Write-Error "Training failed for one or more markets."
    exit $LASTEXITCODE
}

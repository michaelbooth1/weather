# Roadmap Item 6: Feature-Based Probability Model Evaluation

Generated at: 2026-05-27 15:36:49

This report compares the Leave-One-Out validation performance of the empirical baseline model (Item 2) against the new feature-based ML models:

1. **Multinomial Logistic Regression** (L2 penalty, Softmax probabilities)

2. **HistGradientBoostingClassifier** (Non-linear decision tree ensemble)


| Cutoff Hour | Baseline Log Loss | Baseline Acc | LR Log Loss | LR Acc | HGBC Log Loss | HGBC Acc |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 2.7235 | 17.8% | 2.5432 | 15.6% | 2.6882 | 17.2% |
| 10:00 | 2.5898 | 16.6% | 2.4993 | 16.3% | 2.5868 | 17.0% |
| 12:00 | 2.3296 | 18.6% | 2.4028 | 20.1% | 2.2613 | 22.7% |
| 13:00 | 2.1550 | 22.9% | 2.4026 | 15.3% | 2.1015 | 24.5% |
| 15:00 | 1.6903 | 60.1% | 2.3462 | 18.3% | 1.4078 | 52.9% |
| 16:00 | 1.2353 | 81.9% | 2.3344 | 22.9% | 0.9608 | 77.0% |
| 17:00 | 1.0036 | 90.3% | 2.3401 | 21.6% | 0.6912 | 87.0% |
| 18:00 | 0.8895 | 93.7% | 2.3400 | 19.9% | 0.4673 | 94.0% |
| 20:00 | 0.8005 | 96.2% | 2.3635 | 19.8% | 0.3953 | 95.6% |

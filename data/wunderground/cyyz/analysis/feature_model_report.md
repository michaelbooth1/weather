# Roadmap Item 6: Feature-Based Probability Model Evaluation

Generated at: 2026-05-29 22:25:19

This report compares the Leave-One-Out validation performance of the empirical baseline model (Item 2) against the new feature-based ML models:

1. **Multinomial Logistic Regression** (L2 penalty, Softmax probabilities)

2. **HistGradientBoostingClassifier** (Non-linear decision tree ensemble)


Lower log loss / Brier is better. ECE (expected calibration error over the
top-class confidence) is reported per model below the table; lower is better.


| Cutoff Hour | Base LogLoss | Base Brier | Base Acc | LR LogLoss | LR Brier | LR Acc | HGBC LogLoss | HGBC Brier | HGBC Acc |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 2.8716 | 0.9310 | 12.0% | 2.4952 | 0.8988 | 15.6% | 2.6530 | 0.9332 | 18.0% |
| 10:00 | 2.8183 | 0.9243 | 17.6% | 2.4454 | 0.8912 | 16.8% | 2.5505 | 0.9190 | 19.4% |
| 12:00 | 2.7217 | 0.9102 | 24.2% | 2.3604 | 0.8787 | 19.6% | 2.2135 | 0.8637 | 24.7% |
| 13:00 | 2.6315 | 0.8958 | 25.1% | 2.3580 | 0.8822 | 17.7% | 2.0236 | 0.8311 | 27.9% |
| 15:00 | 2.3233 | 0.8322 | 57.0% | 2.3210 | 0.8750 | 19.0% | 1.4387 | 0.6222 | 53.3% |
| 16:00 | 2.0611 | 0.7656 | 80.0% | 2.2948 | 0.8669 | 21.6% | 0.9537 | 0.3678 | 78.0% |
| 17:00 | 1.9196 | 0.7280 | 87.8% | 2.3074 | 0.8684 | 23.4% | 0.6911 | 0.2291 | 87.4% |
| 18:00 | 1.8360 | 0.7070 | 92.4% | 2.2936 | 0.8640 | 23.3% | 0.5046 | 0.1439 | 92.9% |
| 20:00 | 1.7859 | 0.6952 | 94.8% | 2.3168 | 0.8720 | 22.2% | 0.3870 | 0.0959 | 96.0% |

## HGB climatology-blend calibration (tuned by LOO log loss)

Blend weight = fraction on the HGB prediction vs the climatology prior. Previously hardcoded at 0.80 for every hour and ignored at inference; now grid-searched per hour and read from the model bundle.

| Cutoff | Tuned w | LogLoss @0.80 | LogLoss @tuned | Delta | ECE @0.80 | ECE @tuned |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 0.70 | 2.6530 | 2.6480 | +0.0050 | 0.1395 | 0.1135 |
| 10:00 | 0.75 | 2.5505 | 2.5504 | +0.0001 | 0.1415 | 0.1241 |
| 12:00 | 0.95 | 2.2135 | 2.1872 | +0.0264 | 0.1232 | 0.1788 |
| 13:00 | 0.97 | 2.0236 | 1.9754 | +0.0482 | 0.1251 | 0.2001 |
| 15:00 | 0.97 | 1.4387 | 1.3394 | +0.0993 | 0.0693 | 0.0973 |
| 16:00 | 0.97 | 0.9537 | 0.8449 | +0.1088 | 0.1373 | 0.0423 |
| 17:00 | 0.97 | 0.6911 | 0.5661 | +0.1250 | 0.1611 | 0.0324 |
| 18:00 | 0.97 | 0.5046 | 0.3569 | +0.1477 | 0.1784 | 0.0471 |
| 20:00 | 0.97 | 0.3870 | 0.2178 | +0.1692 | 0.1917 | 0.0536 |

## Overall calibration (Expected Calibration Error)

| Model | ECE (top-class confidence vs accuracy) |
| :--- | :--- |
| Empirical baseline | 0.4022 |
| Logistic Regression | 0.0430 |
| HGBC (fixed 0.80 blend) | 0.1046 |
| HGBC (tuned blend) | 0.0802 |

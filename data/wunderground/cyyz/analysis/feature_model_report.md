# Roadmap Item 6: Feature-Based Probability Model Evaluation

Generated at: 2026-05-30 17:11:41

This report compares the Leave-One-Out validation performance of the empirical baseline model (Item 2) against the new feature-based ML models:

1. **Multinomial Logistic Regression** (L2 penalty, Softmax probabilities)

2. **HistGradientBoostingClassifier** (Non-linear decision tree ensemble)


Lower log loss / Brier is better. ECE (expected calibration error over the
top-class confidence) is reported per model below the table; lower is better.


| Cutoff Hour | Base LogLoss | Base Brier | Base Acc | LR LogLoss | LR Brier | LR Acc | HGBC LogLoss | HGBC Brier | HGBC Acc |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 2.8734 | 0.9315 | 13.0% | 2.4897 | 0.8975 | 17.9% | 2.5820 | 0.9316 | 15.6% |
| 10:00 | 2.8235 | 0.9251 | 15.1% | 2.4573 | 0.8941 | 15.6% | 2.5296 | 0.9296 | 16.8% |
| 12:00 | 2.7298 | 0.9109 | 22.5% | 2.3801 | 0.8814 | 19.3% | 2.2033 | 0.8695 | 25.8% |
| 13:00 | 2.6305 | 0.8958 | 25.3% | 2.3724 | 0.8835 | 16.7% | 2.0350 | 0.8362 | 28.5% |
| 15:00 | 2.3155 | 0.8304 | 58.3% | 2.3325 | 0.8740 | 22.5% | 1.3944 | 0.6031 | 56.2% |
| 16:00 | 2.0793 | 0.7650 | 80.6% | 2.3100 | 0.8675 | 21.9% | 0.9352 | 0.3523 | 79.2% |
| 17:00 | 1.9368 | 0.7276 | 88.9% | 2.3250 | 0.8706 | 21.9% | 0.6749 | 0.2209 | 88.1% |
| 18:00 | 1.8572 | 0.7087 | 92.6% | 2.3130 | 0.8676 | 22.7% | 0.5064 | 0.1465 | 92.7% |
| 20:00 | 1.8069 | 0.6964 | 94.9% | 2.3420 | 0.8773 | 19.0% | 0.3957 | 0.1004 | 95.4% |

## HGB climatology-blend calibration (tuned by LOO log loss)

Blend weight = fraction on the HGB prediction vs the climatology prior. Previously hardcoded at 0.80 for every hour and ignored at inference; now grid-searched per hour and read from the model bundle.

| Cutoff | Tuned w | LogLoss @0.80 | LogLoss @tuned | Delta | ECE @0.80 | ECE @tuned |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 09:00 | 0.80 | 2.5820 | 2.5820 | +0.0000 | 0.1697 | 0.1697 |
| 10:00 | 0.80 | 2.5296 | 2.5296 | +0.0000 | 0.1738 | 0.1738 |
| 12:00 | 0.97 | 2.2033 | 2.1648 | +0.0385 | 0.1215 | 0.1863 |
| 13:00 | 0.97 | 2.0350 | 1.9771 | +0.0579 | 0.1185 | 0.1921 |
| 15:00 | 0.97 | 1.3944 | 1.2877 | +0.1067 | 0.0455 | 0.0757 |
| 16:00 | 0.97 | 0.9352 | 0.8194 | +0.1157 | 0.1486 | 0.0449 |
| 17:00 | 0.97 | 0.6749 | 0.5430 | +0.1319 | 0.1564 | 0.0179 |
| 18:00 | 0.97 | 0.5064 | 0.3525 | +0.1538 | 0.1734 | 0.0414 |
| 20:00 | 0.97 | 0.3957 | 0.2227 | +0.1730 | 0.1963 | 0.0553 |

## Overall calibration (Expected Calibration Error)

| Model | ECE (top-class confidence vs accuracy) |
| :--- | :--- |
| Empirical baseline | 0.4026 |
| Logistic Regression | 0.0481 |
| HGBC (fixed 0.80 blend) | 0.1095 |
| HGBC (tuned blend) | 0.0933 |
